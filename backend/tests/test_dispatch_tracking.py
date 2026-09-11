from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from app.db import session_scope
from app.models import (
    BuyerRequirement,
    Dispatch,
    DispatchDriverAssignment,
    DispatchLocation,
    Membership,
    Order,
    OrderGroup,
    Organization,
    OutboxJob,
    Quotation,
    User,
)


PASSWORD = "TrackingTest!2026"


def _user(db, email, role, organization):
    user = User(email=email, full_name=email.split("@")[0], password_hash=generate_password_hash(PASSWORD), phone="+91 90000 00000")
    db.add(user); db.flush()
    db.add(Membership(user_id=user.id, organization_id=organization.id, role=role))
    return user


def _tracking_story(app):
    suffix = uuid.uuid4().hex[:8]
    with app.app_context(), session_scope(app) as db:
        buyer_org = Organization(name=f"Buyer {suffix}", org_type="buyer", location="Vijayawada", latitude=16.5062, longitude=80.6480)
        supplier_org = Organization(name=f"Farm {suffix}", org_type="farm", location="Mangalagiri", latitude=16.4300, longitude=80.5680)
        transport_org = Organization(name=f"Transport {suffix}", org_type="transport", location="Vijayawada")
        outsider_org = Organization(name=f"Outside {suffix}", org_type="buyer", location="Kurnool")
        db.add_all([buyer_org, supplier_org, transport_org, outsider_org]); db.flush()
        buyer = _user(db, f"buyer-{suffix}@test.local", "buyer", buyer_org)
        farmer = _user(db, f"farmer-{suffix}@test.local", "farmer", supplier_org)
        driver = _user(db, f"driver-{suffix}@test.local", "driver", transport_org)
        other_driver = _user(db, f"other-driver-{suffix}@test.local", "driver", transport_org)
        outsider = _user(db, f"outsider-{suffix}@test.local", "buyer", outsider_org)
        requirement = BuyerRequirement(buyer_organization_id=buyer_org.id, created_by_user_id=buyer.id, crop="Tomato", variety="Arka", quantity_kg=100, acceptable_quality="A", destination="Buyer Yard", destination_latitude=16.5062, destination_longitude=80.6480, delivery_mode="seller_delivery", delivery_deadline=date.today()+timedelta(days=2), status="partially_fulfilled")
        db.add(requirement); db.flush()
        quote = Quotation(requirement_id=requirement.id, supplier_organization_id=supplier_org.id, status="accepted")
        db.add(quote); db.flush()
        group = OrderGroup(requirement_id=requirement.id, buyer_organization_id=buyer_org.id, status="confirmed")
        db.add(group); db.flush()
        order = Order(order_number=f"TRACK-{suffix}", order_group_id=group.id, requirement_id=requirement.id, quotation_id=quote.id, buyer_organization_id=buyer_org.id, supplier_organization_id=supplier_org.id, status="dispatched", payment_status="unpaid", delivery_deadline=requirement.delivery_deadline, delivery_mode="seller_delivery")
        db.add(order); db.flush()
        dispatches = [Dispatch(order_id=order.id, reference=f"VEH-{suffix}-1"), Dispatch(order_id=order.id, reference=f"VEH-{suffix}-2")]
        db.add_all(dispatches); db.flush()
        for index, dispatch in enumerate(dispatches):
            db.add(DispatchDriverAssignment(dispatch_id=dispatch.id, driver_user_id=driver.id, assigned_by_user_id=farmer.id, vehicle_registration=f"AP16TEST{index+1}"))
        return {
            "order_id": str(order.id), "dispatch_ids": [str(item.id) for item in dispatches],
            "buyer": buyer.email, "driver": driver.email, "other_driver": other_driver.email, "outsider": outsider.email,
        }


def _login(app, email):
    client = app.test_client()
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client, {"X-CSRF-Token": response.json["csrf_token"]}


def test_dispatch_tracking_access_multiple_dispatches_and_driver_role_isolation(app):
    story = _tracking_story(app)
    driver, driver_headers = _login(app, story["driver"])
    buyer, _ = _login(app, story["buyer"])
    outsider, _ = _login(app, story["outsider"])
    other_driver, other_headers = _login(app, story["other_driver"])

    listing = driver.get("/api/driver/dispatches")
    assert listing.status_code == 200
    assert {item["dispatch"]["id"] for item in listing.json["items"]} == set(story["dispatch_ids"])
    assert buyer.get(f"/api/dispatches/{story['dispatch_ids'][0]}/tracking").status_code == 200
    assert outsider.get(f"/api/dispatches/{story['dispatch_ids'][0]}/tracking").status_code == 403
    assert other_driver.post(f"/api/dispatches/{story['dispatch_ids'][0]}/tracking/start", json={"mode":"real"}, headers=other_headers).status_code == 403
    assert driver.get("/api/orders").json["items"] == []
    assert driver.post("/api/auth/register", json={}, headers=driver_headers).status_code != 200


def test_location_validation_duplicate_stale_stop_and_arrival_do_not_receive_order(app):
    story = _tracking_story(app); dispatch_id = story["dispatch_ids"][0]
    driver, headers = _login(app, story["driver"])
    assert driver.post(f"/api/dispatches/{dispatch_id}/tracking/start", json={"mode":"simulated"}, headers=headers).status_code == 200
    update_id = str(uuid.uuid4()); now = datetime.now(timezone.utc)
    body = {"latitude":16.45,"longitude":80.59,"accuracy_m":12,"captured_at":now.isoformat(),"client_update_id":update_id}
    assert driver.post(f"/api/dispatches/{dispatch_id}/locations", json={**body,"latitude":91}, headers=headers).status_code == 422
    assert driver.post(f"/api/dispatches/{dispatch_id}/locations", json={**body,"captured_at":(now-timedelta(minutes=3)).isoformat()}, headers=headers).status_code == 409
    created = driver.post(f"/api/dispatches/{dispatch_id}/locations", json=body, headers=headers)
    assert created.status_code == 201 and created.json["simulated"] is True
    duplicate = driver.post(f"/api/dispatches/{dispatch_id}/locations", json=body, headers=headers)
    assert duplicate.status_code == 200 and duplicate.json["duplicate"] is True
    assert driver.post(f"/api/dispatches/{dispatch_id}/tracking/stop", headers=headers).status_code == 200
    stopped_update = driver.post(f"/api/dispatches/{dispatch_id}/locations", json={**body,"captured_at":datetime.now(timezone.utc).isoformat(),"client_update_id":str(uuid.uuid4())}, headers=headers)
    assert stopped_update.status_code == 409
    assert driver.post(f"/api/dispatches/{dispatch_id}/tracking/start", json={"mode":"real"}, headers=headers).status_code == 200
    arrival = driver.post(f"/api/dispatches/{dispatch_id}/tracking/arrival", headers=headers)
    assert arrival.status_code == 200 and arrival.json["dispatch"]["sharing_status"] == "arrived"
    with app.app_context(), session_scope(app) as db:
        assert db.get(Order, uuid.UUID(story["order_id"])).status == "dispatched"
        db.query(OutboxJob).filter(OutboxJob.event_key == f"dispatch:{dispatch_id}:arrived").delete()


def test_delayed_location_is_reported_stale(app):
    story = _tracking_story(app); dispatch_id = uuid.UUID(story["dispatch_ids"][0])
    driver, headers = _login(app, story["driver"]); buyer, _ = _login(app, story["buyer"])
    driver.post(f"/api/dispatches/{dispatch_id}/tracking/start", json={"mode":"simulated"}, headers=headers)
    with app.app_context(), session_scope(app) as db:
        assignment = db.query(DispatchDriverAssignment).filter_by(dispatch_id=dispatch_id).one()
        old = datetime.now(timezone.utc)-timedelta(seconds=30)
        db.add(DispatchLocation(dispatch_id=dispatch_id, driver_user_id=assignment.driver_user_id, latitude=16.45, longitude=80.59, accuracy_m=10, captured_at=old, received_at=old, is_simulated=True, client_update_id=str(uuid.uuid4())))
        assignment.last_location_at = old
    response = buyer.get(f"/api/dispatches/{dispatch_id}/tracking")
    assert response.status_code == 200
    assert response.json["tracking_health"] == "stale"
