from datetime import date, timedelta
from datetime import datetime, timezone
import io
import uuid


PASSWORD = "StrongDemoPass!2026"


def register(client, *, email, role, organization):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": email.split("@")[0].title(),
            "organization_name": organization,
            "location": "Guntur, Andhra Pradesh",
            "role": role,
        },
    )
    assert response.status_code == 201
    return response.json["csrf_token"]


def mutation(client, path, csrf, body, **headers):
    return client.post(path, json=body, headers={"X-CSRF-Token": csrf, **headers})


def marketplace_story(app, submit_offer=True):
    suffix = uuid.uuid4().hex[:8]
    buyer = app.test_client()
    farmer = app.test_client()
    outsider = app.test_client()
    buyer_csrf = register(buyer, email=f"neg-buyer-{suffix}@example.com", role="buyer", organization=f"Negotiation Buyer {suffix}")
    farmer_csrf = register(farmer, email=f"neg-farmer-{suffix}@example.com", role="farmer", organization=f"Negotiation Farm {suffix}")
    outsider_csrf = register(outsider, email=f"neg-outsider-{suffix}@example.com", role="buyer", organization=f"Unrelated Buyer {suffix}")

    deadline = (date.today() + timedelta(days=10)).isoformat()
    requirement = mutation(
        buyer,
        "/api/requirements",
        buyer_csrf,
        {"crop": "Tomato", "variety": "Arka Rakshak", "quantity_kg": 100, "acceptable_quality": "B", "destination": "Vijayawada", "delivery_mode": "buyer_pickup", "delivery_deadline": deadline, "budget_price_inr": 25, "notes": "Test requirement"},
    )
    assert requirement.status_code == 201
    lot = mutation(
        farmer,
        "/api/produce",
        farmer_csrf,
        {"crop": "Tomato", "variety": "Arka Rakshak", "quality_grade": "A", "quantity_kg": 100, "asking_price_inr": 24, "location": "Guntur", "delivery_mode": "buyer_pickup", "harvest_date": date.today().isoformat(), "available_from": date.today().isoformat(), "available_until": deadline, "description": "Test lot"},
    )
    assert lot.status_code == 201
    capture = mutation(farmer, f"/api/produce/{lot.json['id']}/photo-capture-session", farmer_csrf, {})
    photo = farmer.post(
        f"/api/produce/{lot.json['id']}/photo",
        data={"capture_token": capture.json["capture_token"], "latitude": "16.3", "longitude": "80.4", "accuracy_m": "25", "captured_at": datetime.now(timezone.utc).isoformat(), "photo": (io.BytesIO(b"\xff\xd8\xffcamera"), "camera.jpg", "image/jpeg")},
        headers={"X-CSRF-Token": farmer_csrf},
    )
    assert photo.status_code == 200
    quote = None
    if submit_offer:
        quote = mutation(
            farmer,
            f"/api/requirements/{requirement.json['id']}/quotations",
            farmer_csrf,
            {"allocations": [{"produce_lot_id": lot.json["id"], "quantity_kg": 100}], "price_inr_per_kg": 24, "quality_grade": "A", "delivery_date": deadline, "delivery_terms": "Crate delivery", "note": "Initial offer"},
        )
        assert quote.status_code == 201
    return buyer, farmer, outsider, buyer_csrf, farmer_csrf, outsider_csrf, requirement.json, lot.json, quote.json if quote else None


def test_eligible_lots_and_strict_offer_validation(app):
    buyer, farmer, outsider, _, farmer_csrf, _, requirement, lot, _ = marketplace_story(app, submit_offer=False)
    incompatible = mutation(
        farmer,
        "/api/produce",
        farmer_csrf,
        {"crop": "Onion", "variety": "Nasik Red", "quality_grade": "A", "quantity_kg": 200, "asking_price_inr": 20, "location": "Guntur", "delivery_mode": "buyer_pickup", "harvest_date": date.today().isoformat(), "available_from": date.today().isoformat(), "available_until": requirement["delivery_deadline"], "description": "Wrong crop"},
    )
    assert incompatible.status_code == 201

    eligible = farmer.get(f"/api/requirements/{requirement['id']}/eligible-lots")
    assert eligible.status_code == 200
    assert [item["id"] for item in eligible.json["items"]] == [lot["id"]]
    assert eligible.json["remaining_requirement_kg"] == 100
    assert eligible.json["existing_negotiations"] == []
    assert outsider.get(f"/api/requirements/{requirement['id']}/eligible-lots").status_code == 403

    base_offer = {"allocations": [{"produce_lot_id": lot["id"], "quantity_kg": 100}], "price_inr_per_kg": 24, "delivery_date": requirement["delivery_deadline"], "delivery_terms": "Crate delivery", "note": "Initial offer"}
    too_much = mutation(farmer, f"/api/requirements/{requirement['id']}/quotations", farmer_csrf, {**base_offer, "allocations": [{"produce_lot_id": lot["id"], "quantity_kg": 101}]})
    assert too_much.status_code == 422 and "available" in too_much.json["message"]
    bad_price = mutation(farmer, f"/api/requirements/{requirement['id']}/quotations", farmer_csrf, {**base_offer, "price_inr_per_kg": "24.999"})
    assert bad_price.status_code == 422 and "decimal places" in bad_price.json["message"]
    wrong_crop = mutation(farmer, f"/api/requirements/{requirement['id']}/quotations", farmer_csrf, {**base_offer, "allocations": [{"produce_lot_id": incompatible.json["id"], "quantity_kg": 50}]})
    assert wrong_crop.status_code == 422

    accepted = mutation(farmer, f"/api/requirements/{requirement['id']}/quotations", farmer_csrf, base_offer)
    assert accepted.status_code == 201
    after = farmer.get(f"/api/requirements/{requirement['id']}/eligible-lots").json
    assert after["existing_negotiations"][0]["id"] == accepted.json["id"]
    repeated = mutation(farmer, f"/api/requirements/{requirement['id']}/quotations", farmer_csrf, base_offer)
    assert repeated.status_code == 409


def test_counter_chat_permissions_and_order_confirmation(app):
    buyer, farmer, outsider, buyer_csrf, farmer_csrf, _, requirement, _, quote = marketplace_story(app)
    quote_id = quote["id"]
    detail = buyer.get(f"/api/quotations/{quote_id}")
    assert detail.status_code == 200
    assert detail.json["actions"]["can_counter"] is True
    assert outsider.get(f"/api/quotations/{quote_id}").status_code == 403

    first_message = mutation(buyer, f"/api/quotations/{quote_id}/messages", buyer_csrf, {"body": "Can you deliver by morning?", "client_message_id": "message-one"})
    assert first_message.status_code == 201
    duplicate = mutation(buyer, f"/api/quotations/{quote_id}/messages", buyer_csrf, {"body": "Can you deliver by morning?", "client_message_id": "message-one"})
    assert duplicate.status_code == 200 and duplicate.json["duplicate"] is True
    conflict = mutation(buyer, f"/api/quotations/{quote_id}/messages", buyer_csrf, {"body": "Different content", "client_message_id": "message-one"})
    assert conflict.status_code == 409

    counter = mutation(
        buyer,
        f"/api/quotations/{quote_id}/counter",
        buyer_csrf,
        {"version": detail.json["version"], "quantity_kg": 80, "price_inr_per_kg": 23, "quality_grade": "A", "delivery_date": requirement["delivery_deadline"], "delivery_terms": "Crate delivery before noon", "note": "Buyer counter"},
    )
    assert counter.status_code == 201 and counter.json["status"] == "awaiting_supplier"
    stale_or_same_side = mutation(
        buyer,
        f"/api/quotations/{quote_id}/counter",
        buyer_csrf,
        {"version": counter.json["version"], "quantity_kg": 70, "price_inr_per_kg": 22, "quality_grade": "A", "delivery_date": requirement["delivery_deadline"], "delivery_terms": "Same side retry"},
    )
    assert stale_or_same_side.status_code == 409

    agreed = mutation(farmer, f"/api/quotations/{quote_id}/accept-terms", farmer_csrf, {"version": counter.json["version"]})
    assert agreed.status_code == 200 and agreed.json["status"] == "agreed"
    confirm = mutation(
        buyer,
        f"/api/requirements/{requirement['id']}/confirm",
        buyer_csrf,
        {"quotation_ids": [quote_id]},
        **{"Idempotency-Key": "confirm-negotiated-order"},
    )
    assert confirm.status_code == 201
    replay = mutation(
        buyer,
        f"/api/requirements/{requirement['id']}/confirm",
        buyer_csrf,
        {"quotation_ids": [quote_id]},
        **{"Idempotency-Key": "confirm-negotiated-order"},
    )
    assert replay.status_code == 201
    assert replay.json["orders"] == confirm.json["orders"]
    assert len(confirm.json["orders"]) == 1


def test_buyer_counter_cannot_increase_supplier_quantity(app):
    buyer, _, _, buyer_csrf, _, _, requirement, _, quote = marketplace_story(app)
    detail = buyer.get(f"/api/quotations/{quote['id']}").json
    response = mutation(
        buyer,
        f"/api/quotations/{quote['id']}/counter",
        buyer_csrf,
        {"version": detail["version"], "quantity_kg": 101, "price_inr_per_kg": 23, "quality_grade": "A", "delivery_date": requirement["delivery_deadline"], "delivery_terms": "Invalid increase"},
    )
    assert response.status_code == 422


def test_assistant_is_optional_and_scoped(app):
    buyer, _, outsider, buyer_csrf, _, outsider_csrf, requirement, _, _ = marketplace_story(app)
    disabled = mutation(buyer, "/api/assistant/procurement", buyer_csrf, {"mode": "analyze", "message": "Summarize supply", "requirement_id": requirement["id"]})
    assert disabled.status_code == 200
    assert disabled.json["source"] == "rule_based"
    hidden = mutation(outsider, "/api/assistant/procurement", outsider_csrf, {"mode": "analyze", "message": "Show another buyer's data", "requirement_id": requirement["id"]})
    assert hidden.status_code == 404


def test_assistant_returns_grounded_structured_result(app, monkeypatch):
    buyer, _, _, buyer_csrf, _, _, requirement, _, _ = marketplace_story(app)

    def fake_generation(**kwargs):
        assert kwargs["context"]["requirement"]["id"] == requirement["id"]
        assert kwargs["mode"] == "draft_requirement"
        return {
            "answer": "The saved requirement can be split across compatible suppliers.",
            "suggestions": ["Review the deterministic matches before confirming."],
            "warnings": ["No stock is reserved by this assistant."],
            "draft": {
                "crop": "Tomato",
                "variety": "Arka Rakshak",
                "quantity_kg": 100,
                "acceptable_quality": "A",
                "destination": "Vijayawada",
                "delivery_deadline": requirement["delivery_deadline"],
                "budget_price_inr": 25,
                "notes": "Morning delivery preferred.",
            },
            "model": "test-mistral",
        }

    monkeypatch.setattr("app.routes.assistant.generate_procurement_advice", fake_generation)
    response = mutation(
        buyer,
        "/api/assistant/procurement",
        buyer_csrf,
        {"mode": "draft_requirement", "message": "Draft a tomato requirement", "requirement_id": requirement["id"]},
    )
    assert response.status_code == 200
    assert response.json["draft"]["crop"] == "Tomato"
    assert response.json["model"] == "test-mistral"


def test_camera_capture_is_single_use_and_listing_archive_is_reversible(app):
    _, farmer, outsider, _, farmer_csrf, _, _, lot, _ = marketplace_story(app, submit_offer=False)
    current = next(item for item in farmer.get("/api/produce?mine=true").json["items"] if item["id"] == lot["id"])
    assert current["status"] == "active" and current["location_recorded"] is True
    capture = mutation(farmer, f"/api/produce/{lot['id']}/photo-capture-session", farmer_csrf, {})
    payload = {"capture_token": capture.json["capture_token"], "latitude": "16.3", "longitude": "80.4", "accuracy_m": "25", "captured_at": datetime.now(timezone.utc).isoformat(), "photo": (io.BytesIO(b"\xff\xd8\xffagain"), "camera.jpg", "image/jpeg")}
    assert farmer.post(f"/api/produce/{lot['id']}/photo", data=payload, headers={"X-CSRF-Token": farmer_csrf}).status_code == 200
    reused = {**payload, "photo": (io.BytesIO(b"\xff\xd8\xffagain"), "camera.jpg", "image/jpeg")}
    assert farmer.post(f"/api/produce/{lot['id']}/photo", data=reused, headers={"X-CSRF-Token": farmer_csrf}).status_code == 409
    current = next(item for item in farmer.get("/api/produce?mine=true").json["items"] if item["id"] == lot["id"])
    archived = mutation(farmer, f"/api/produce/{lot['id']}/archive", farmer_csrf, {"version": current["version"]})
    assert archived.status_code == 200 and archived.json["status"] == "archived"
    assert lot["id"] not in {item["id"] for item in outsider.get("/api/produce").json["items"]}
    restored = mutation(farmer, f"/api/produce/{lot['id']}/restore", farmer_csrf, {"version": archived.json["version"]})
    assert restored.status_code == 200 and restored.json["status"] == "active"


def test_tracking_and_complaint_permissions(app):
    buyer, farmer, outsider, buyer_csrf, farmer_csrf, outsider_csrf, requirement, _, quote = marketplace_story(app)
    confirmed = mutation(buyer, f"/api/requirements/{requirement['id']}/confirm", buyer_csrf, {"quotation_ids": [quote["id"]]}, **{"Idempotency-Key": "tracking-confirm"})
    order_id = confirmed.json["orders"][0]["order_id"]
    order = farmer.get(f"/api/orders/{order_id}").json
    preparing = mutation(farmer, f"/api/orders/{order_id}/tracking", farmer_csrf, {"version": order["version"], "status": "preparing", "note": "Packing produce"})
    assert preparing.status_code == 201
    invalid = mutation(farmer, f"/api/orders/{order_id}/tracking", farmer_csrf, {"version": preparing.json["version"], "status": "arrived", "note": "Skipped states"})
    assert invalid.status_code == 409
    complaint = mutation(buyer, f"/api/orders/{order_id}/disputes", buyer_csrf, {"category": "crop_damage", "affected_quantity_kg": 4, "reason": "Four kilograms were visibly damaged.", "requested_resolution": "Review a deduction."})
    assert complaint.status_code == 201
    assert mutation(outsider, f"/api/orders/{order_id}/disputes", outsider_csrf, {"category": "other", "reason": "This unrelated buyer cannot report the order."}).status_code == 403
