from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import create_app
from app.db import Base, session_scope
from app.models import (
    AuditEvent, BuyerRequirement, Dispatch, DispatchDriverAssignment, DispatchLine, DispatchLocation, Dispute, FpoAuthorization, Membership,
    Order, OrderGroup, OrderLine, OrderRating, Organization, OutboxJob, PaymentEvent, ProduceLot,
    Quotation, QuoteAllocation, QuoteRevision, Receipt, ReceiptLine, StockReservation, User,
    UserSession, TrackingEvent,
)


DEMO_PASSWORD = os.getenv("DEMO_PASSWORD") or "AgriLinkDemo!2026"
DEMO_EMAILS = {
    "admin@agrilink.demo",
    "buyer@agrilink.demo",
    "outsider@agrilink.demo",
    "fpo@agrilink.demo",
    "farmer.a@agrilink.demo",
    "farmer.b@agrilink.demo",
    "farmer.c@agrilink.demo",
    "driver@agrilink.demo",
    "driver.two@agrilink.demo",
}


def demo_mode_enabled():
    return os.getenv("AGRILINK_ENV") == "demo" or os.getenv("DEMO_MODE", "false").lower() == "true"


def create_user(db, email, name, role, org):
    user = User(email=email, full_name=name, password_hash=generate_password_hash(DEMO_PASSWORD), locale="en")
    db.add(user); db.flush()
    db.add(Membership(user_id=user.id, organization_id=org.id, role=role))
    return user


def repair_demo_accounts(db):
    if len(DEMO_PASSWORD) < 12:
        raise SystemExit("DEMO_PASSWORD must contain at least 12 characters.")
    users = db.query(User).filter(User.email.in_(DEMO_EMAILS)).all()
    found = {user.email for user in users}
    missing = sorted(DEMO_EMAILS - found)
    if missing:
        raise SystemExit("Demo repair refused because accounts are missing: " + ", ".join(missing))
    for user in users:
        user.password_hash = generate_password_hash(DEMO_PASSWORD)
        user.is_active = True
        for session in db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)):
            session.revoked_at = datetime.now(timezone.utc)
    db.add(AuditEvent(action="demo.accounts_repaired", entity_type="system", details={"accounts": len(users)}))
    return len(users)


def ensure_tracking_demo(db):
    """Add driver-only demo accounts and bind existing demo dispatches without resetting data."""
    transport = db.query(Organization).filter_by(name="Krishna Route Logistics").first()
    if not transport:
        transport = Organization(name="Krishna Route Logistics", org_type="transport", location="Vijayawada, Andhra Pradesh", verified_at=datetime.now(timezone.utc), verification_note="Demo transport operator")
        db.add(transport); db.flush()
    driver_specs = [
        ("driver@agrilink.demo", "Ramesh Driver", "+91 90000 10001"),
        ("driver.two@agrilink.demo", "Kiran Driver", "+91 90000 10002"),
    ]
    drivers = []
    for email, name, phone in driver_specs:
        user = db.query(User).filter_by(email=email).first()
        if not user:
            user = create_user(db, email, name, "driver", transport)
        elif not db.query(Membership).filter_by(user_id=user.id, role="driver", is_active=True).first():
            db.add(Membership(user_id=user.id, organization_id=transport.id, role="driver"))
        user.full_name = name; user.phone = phone; user.password_hash = generate_password_hash(DEMO_PASSWORD); user.is_active = True
        drivers.append(user)
    admin = db.query(User).filter_by(email="admin@agrilink.demo").first() or drivers[0]
    dispatches = db.query(Dispatch).order_by(Dispatch.dispatched_at).all()
    assigned = 0
    for index, dispatch in enumerate(dispatches):
        if db.query(DispatchDriverAssignment).filter_by(dispatch_id=dispatch.id).first():
            continue
        terminal = dispatch.status == "arrived" or db.query(Order).filter_by(id=dispatch.order_id, status="received").first() is not None
        db.add(DispatchDriverAssignment(
            dispatch_id=dispatch.id,
            driver_user_id=drivers[index % len(drivers)].id,
            assigned_by_user_id=admin.id,
            vehicle_registration=(dispatch.reference or f"DEMO-{index + 1}")[:40],
            tracking_mode="simulated",
            sharing_status="arrived" if terminal else "not_started",
            arrived_at=datetime.now(timezone.utc) if terminal else None,
            stopped_at=datetime.now(timezone.utc) if terminal else None,
        ))
        assigned += 1
    db.add(AuditEvent(actor_user_id=admin.id, action="demo.tracking_ready", entity_type="system", details={"drivers": len(drivers), "dispatches_assigned": assigned}))
    return len(drivers), assigned


def seed(db):
    today = date.today()
    platform = Organization(name="AgriLink Demo Administration", org_type="platform", location="Vijayawada, Andhra Pradesh", verified_at=datetime.now(timezone.utc), verification_note="Demo platform record")
    buyer_org = Organization(name="Coastal Fresh Wholesale", org_type="buyer", location="Vijayawada, Andhra Pradesh", latitude=Decimal("16.5062"), longitude=Decimal("80.6480"), verified_at=datetime.now(timezone.utc), verification_note="Demo verification")
    unrelated_org = Organization(name="Rayalaseema Kitchens", org_type="buyer", location="Kurnool, Andhra Pradesh")
    fpo = Organization(name="Krishna Delta FPO", org_type="fpo", location="Guntur, Andhra Pradesh", verified_at=datetime.now(timezone.utc), verification_note="Demo FPO verification")
    farm_a = Organization(name="Lakshmi Farm", org_type="farm", location="Tenali, Andhra Pradesh", latitude=Decimal("16.2430"), longitude=Decimal("80.6400"), verified_at=datetime.now(timezone.utc), verification_note="Demo farm verification")
    farm_b = Organization(name="Ravi Natural Produce", org_type="farm", location="Mangalagiri, Andhra Pradesh", latitude=Decimal("16.4300"), longitude=Decimal("80.5680"))
    farm_c = Organization(name="Annapurna Fields", org_type="farm", location="Amaravati, Andhra Pradesh", latitude=Decimal("16.5730"), longitude=Decimal("80.3580"))
    transport = Organization(name="Krishna Route Logistics", org_type="transport", location="Vijayawada, Andhra Pradesh", verified_at=datetime.now(timezone.utc), verification_note="Demo transport operator")
    db.add_all([platform, buyer_org, unrelated_org, fpo, farm_a, farm_b, farm_c, transport]); db.flush()

    admin = create_user(db, "admin@agrilink.demo", "Ananya Rao", "admin", platform)
    buyer = create_user(db, "buyer@agrilink.demo", "Meera Reddy", "buyer", buyer_org)
    create_user(db, "outsider@agrilink.demo", "Vikram Naidu", "buyer", unrelated_org)
    fpo_manager = create_user(db, "fpo@agrilink.demo", "Suresh Babu", "fpo_manager", fpo)
    farmer_a = create_user(db, "farmer.a@agrilink.demo", "Lakshmi Devi", "farmer", farm_a)
    farmer_b = create_user(db, "farmer.b@agrilink.demo", "Ravi Kumar", "farmer", farm_b)
    farmer_c = create_user(db, "farmer.c@agrilink.demo", "Padma Rao", "farmer", farm_c)
    driver = create_user(db, "driver@agrilink.demo", "Ramesh Driver", "driver", transport)
    driver.phone = "+91 90000 10001"
    driver_two = create_user(db, "driver.two@agrilink.demo", "Kiran Driver", "driver", transport)
    driver_two.phone = "+91 90000 10002"

    for farm in (farm_a, farm_b, farm_c):
        db.add(FpoAuthorization(fpo_organization_id=fpo.id, farmer_organization_id=farm.id, granted_by_user_id=admin.id))

    lots = [
        ProduceLot(farmer_organization_id=farm_a.id, created_by_user_id=farmer_a.id, crop="Tomato", variety="Arka Rakshak", quality_grade="A", quantity_on_hand_kg=Decimal("400"), asking_price_paise=1800, location=farm_a.location, harvest_date=today- timedelta(days=1), available_from=today, available_until=today+timedelta(days=18), description="Firm, evenly ripened table tomatoes.", photo_path="tomatoes.png"),
        ProduceLot(farmer_organization_id=farm_b.id, created_by_user_id=farmer_b.id, crop="Tomato", variety="Arka Rakshak", quality_grade="A", quantity_on_hand_kg=Decimal("350"), asking_price_paise=1900, location=farm_b.location, harvest_date=today, available_from=today, available_until=today+timedelta(days=18), description="Morning harvest packed in ventilated crates.", photo_path="tomatoes.png"),
        ProduceLot(farmer_organization_id=farm_c.id, created_by_user_id=farmer_c.id, crop="Tomato", variety="Arka Rakshak", quality_grade="B", quantity_on_hand_kg=Decimal("500"), asking_price_paise=2800, location=farm_c.location, harvest_date=today+timedelta(days=11), available_from=today+timedelta(days=13), available_until=today+timedelta(days=25), description="Scheduled harvest with flexible packing.", photo_path="tomato-field.png"),
        ProduceLot(farmer_organization_id=farm_a.id, created_by_user_id=farmer_a.id, crop="Green Chilli", variety="Teja", quality_grade="A", quantity_on_hand_kg=Decimal("620"), asking_price_paise=5200, location=farm_a.location, harvest_date=today- timedelta(days=1), available_from=today, available_until=today+timedelta(days=10), description="Fresh pungent Teja chillies.", photo_path="chillies.png"),
        ProduceLot(farmer_organization_id=farm_b.id, created_by_user_id=farmer_b.id, crop="Onion", variety="Nasik Red", quality_grade="B", quantity_on_hand_kg=Decimal("900"), asking_price_paise=2400, location=farm_b.location, harvest_date=today- timedelta(days=3), available_from=today, available_until=today+timedelta(days=30), description="Cured red onions suitable for wholesale.", photo_path="onions.png"),
    ]
    for lot, farm in zip(lots, (farm_a, farm_b, farm_c, farm_a, farm_b)):
        lot.delivery_mode = "seller_delivery"
        lot.delivery_service_location = "Vijayawada, Andhra Pradesh"
        lot.delivery_radius_km = Decimal("100")
        lot.delivery_charge_paise = 15000
        lot.latitude = farm.latitude
        lot.longitude = farm.longitude
    db.add_all(lots); db.flush()

    tomato_req = BuyerRequirement(buyer_organization_id=buyer_org.id, created_by_user_id=buyer.id, crop="Tomato", variety="Arka Rakshak", quantity_kg=Decimal("1000"), acceptable_quality="B", destination="Coastal Fresh Yard, Vijayawada", destination_latitude=buyer_org.latitude, destination_longitude=buyer_org.longitude, delivery_mode="seller_delivery", delivery_deadline=today+timedelta(days=14), budget_price_paise=2500, notes="Demo requirement: ventilated crates, morning delivery.")
    onion_req = BuyerRequirement(buyer_organization_id=buyer_org.id, created_by_user_id=buyer.id, crop="Onion", variety="Nasik Red", quantity_kg=Decimal("700"), acceptable_quality="B", destination="Gollapudi Market Yard, Vijayawada", destination_latitude=buyer_org.latitude, destination_longitude=buyer_org.longitude, delivery_mode="seller_delivery", delivery_deadline=today+timedelta(days=12), budget_price_paise=2600, notes="Dry, cured bulbs only.")
    db.add_all([tomato_req, onion_req]); db.flush()

    for lot, farmer, quantity, price in ((lots[0], farmer_a, 400, 1850), (lots[1], farmer_b, 350, 1900), (lots[2], farmer_c, 250, 2400)):
        quote = Quotation(requirement_id=tomato_req.id, supplier_organization_id=lot.farmer_organization_id, status="awaiting_buyer")
        db.add(quote); db.flush()
        revision = QuoteRevision(quotation_id=quote.id, revision_number=1, actor_user_id=farmer.id, actor_organization_id=lot.farmer_organization_id, action="offer", offered_quantity_kg=Decimal(quantity), price_paise_per_kg=price, quality_grade=lot.quality_grade, delivery_date=tomato_req.delivery_deadline, delivery_terms="Supplier delivery in ventilated crates", delivery_mode="seller_delivery", delivery_charge_paise=15000, note="Fictional demo quotation")
        db.add(revision); db.flush()
        db.add(QuoteAllocation(quote_revision_id=revision.id, produce_lot_id=lot.id, farmer_organization_id=lot.farmer_organization_id, quantity_kg=Decimal(quantity)))

    # A separate in-progress order makes fulfillment, payment, and deadline screens useful immediately.
    group = OrderGroup(requirement_id=onion_req.id, buyer_organization_id=buyer_org.id, status="confirmed")
    db.add(group); db.flush()
    quote = Quotation(requirement_id=onion_req.id, supplier_organization_id=farm_b.id, coordinating_fpo_id=fpo.id, status="accepted")
    db.add(quote); db.flush()
    rev = QuoteRevision(quotation_id=quote.id, revision_number=1, actor_user_id=fpo_manager.id, actor_organization_id=fpo.id, action="offer", offered_quantity_kg=Decimal("500"), price_paise_per_kg=2350, quality_grade="B", delivery_date=today+timedelta(days=3), delivery_terms="FPO coordinated delivery", delivery_mode="seller_delivery", delivery_charge_paise=15000, note="Sample accepted quotation")
    db.add(rev); db.flush(); db.add(QuoteAllocation(quote_revision_id=rev.id, produce_lot_id=lots[4].id, farmer_organization_id=farm_b.id, quantity_kg=Decimal("500")))
    order = Order(order_number=f"AG-DEMO-{today:%m%d}-01", order_group_id=group.id, requirement_id=onion_req.id, quotation_id=quote.id, buyer_organization_id=buyer_org.id, supplier_organization_id=farm_b.id, coordinating_fpo_id=fpo.id, status="partially_received", payment_status="partially_paid", delivery_deadline=today+timedelta(days=3), delivery_mode="seller_delivery", delivery_charge_paise=15000)
    db.add(order); db.flush()
    line = OrderLine(order_id=order.id, produce_lot_id=lots[4].id, farmer_organization_id=farm_b.id, crop="Onion", variety="Nasik Red", quality_grade="B", agreed_quantity_kg=Decimal("500"), agreed_price_paise_per_kg=2350, delivery_terms="FPO coordinated delivery")
    db.add(line); db.flush(); stock_reservation = StockReservation(order_line_id=line.id, produce_lot_id=lots[4].id, reserved_quantity_kg=Decimal("500"), dispatched_quantity_kg=Decimal("300"), status="active"); db.add(stock_reservation); lots[4].quantity_on_hand_kg -= Decimal("300")
    dispatch = Dispatch(order_id=order.id, reference="AP16-DEMO-TRUCK", note="Fictional dispatch")
    db.add(dispatch); db.flush(); db.add(DispatchLine(dispatch_id=dispatch.id, order_line_id=line.id, quantity_kg=Decimal("300")))
    db.add(DispatchDriverAssignment(dispatch_id=dispatch.id, driver_user_id=driver.id, assigned_by_user_id=farmer_b.id, vehicle_registration="AP16-DEMO-01", tracking_mode="simulated", sharing_status="not_started"))
    second_dispatch = Dispatch(order_id=order.id, reference="AP16-DEMO-VAN", note="Second fictional vehicle demonstrates per-dispatch tracking")
    db.add(second_dispatch); db.flush(); db.add(DispatchLine(dispatch_id=second_dispatch.id, order_line_id=line.id, quantity_kg=Decimal("100")))
    db.add(DispatchDriverAssignment(dispatch_id=second_dispatch.id, driver_user_id=driver_two.id, assigned_by_user_id=farmer_b.id, vehicle_registration="AP16-DEMO-02", tracking_mode="simulated", sharing_status="not_started"))
    # Account for the second vehicle without changing the partial receipt.
    stock_reservation.dispatched_quantity_kg = Decimal("400")
    lots[4].quantity_on_hand_kg -= Decimal("100")
    receipt = Receipt(order_id=order.id, recorded_by_user_id=buyer.id, note="Partial receipt accepted")
    db.add(receipt); db.flush(); db.add(ReceiptLine(receipt_id=receipt.id, order_line_id=line.id, quantity_kg=Decimal("220"), deduction_paise=15000, deduction_reason="Damaged outer bags"))
    db.add(PaymentEvent(order_id=order.id, actor_user_id=buyer.id, amount_paise=400000, outcome="success", external_reference="SIM-DEMO-PARTIAL", note="Simulated payment — no real funds transferred"))
    db.add_all([
        TrackingEvent(order_id=order.id, actor_user_id=farmer_b.id, status="preparing", note="Onions packed for dispatch."),
        TrackingEvent(order_id=order.id, actor_user_id=farmer_b.id, status="in_transit", note="Fictional truck left the farm."),
        TrackingEvent(order_id=order.id, actor_user_id=buyer.id, status="partially_received", note="220 kg recorded as received."),
    ])
    dispute = Dispute(order_id=order.id, opened_by_user_id=buyer.id, category="crop_damage", affected_quantity_kg=Decimal("12"), reason="Some outer onion bags were damaged during the fictional demo delivery.", requested_resolution="Review the recorded deduction.", status="under_review")
    db.add(dispute)
    onion_req.status = "partially_fulfilled"

    # A completed FPO-coordinated order makes the dual farmer/FPO review flow demo-ready.
    completed_req = BuyerRequirement(buyer_organization_id=buyer_org.id, created_by_user_id=buyer.id, crop="Green Chilli", variety="Teja", quantity_kg=Decimal("100"), acceptable_quality="A", destination="Coastal Fresh Yard, Vijayawada", destination_latitude=buyer_org.latitude, destination_longitude=buyer_org.longitude, delivery_mode="seller_delivery", delivery_deadline=today+timedelta(days=7), budget_price_paise=5500, notes="Completed fictional order available for review.", status="fulfilled")
    db.add(completed_req); db.flush()
    completed_group = OrderGroup(requirement_id=completed_req.id, buyer_organization_id=buyer_org.id, status="confirmed")
    db.add(completed_group); db.flush()
    completed_quote = Quotation(requirement_id=completed_req.id, supplier_organization_id=farm_a.id, coordinating_fpo_id=fpo.id, status="accepted")
    db.add(completed_quote); db.flush()
    completed_revision = QuoteRevision(quotation_id=completed_quote.id, revision_number=1, actor_user_id=fpo_manager.id, actor_organization_id=fpo.id, action="offer", offered_quantity_kg=Decimal("100"), price_paise_per_kg=5000, quality_grade="A", delivery_date=today-timedelta(days=1), delivery_terms="FPO coordinated crate delivery", delivery_mode="seller_delivery", delivery_charge_paise=10000, note="Completed sample quotation")
    db.add(completed_revision); db.flush()
    db.add(QuoteAllocation(quote_revision_id=completed_revision.id, produce_lot_id=lots[3].id, farmer_organization_id=farm_a.id, quantity_kg=Decimal("100")))
    completed_order = Order(order_number=f"AG-DEMO-{today:%m%d}-02", order_group_id=completed_group.id, requirement_id=completed_req.id, quotation_id=completed_quote.id, buyer_organization_id=buyer_org.id, supplier_organization_id=farm_a.id, coordinating_fpo_id=fpo.id, status="received", payment_status="unpaid", delivery_deadline=today-timedelta(days=1), delivery_mode="seller_delivery", delivery_charge_paise=10000)
    db.add(completed_order); db.flush()
    completed_line = OrderLine(order_id=completed_order.id, produce_lot_id=lots[3].id, farmer_organization_id=farm_a.id, crop="Green Chilli", variety="Teja", quality_grade="A", agreed_quantity_kg=Decimal("100"), agreed_price_paise_per_kg=5000, delivery_terms="FPO coordinated crate delivery")
    db.add(completed_line); db.flush()
    db.add(StockReservation(order_line_id=completed_line.id, produce_lot_id=lots[3].id, reserved_quantity_kg=Decimal("100"), dispatched_quantity_kg=Decimal("100"), status="fulfilled")); lots[3].quantity_on_hand_kg -= Decimal("100")
    completed_dispatch = Dispatch(order_id=completed_order.id, reference="AP16-DEMO-COMPLETE", note="Completed fictional dispatch")
    db.add(completed_dispatch); db.flush(); db.add(DispatchLine(dispatch_id=completed_dispatch.id, order_line_id=completed_line.id, quantity_kg=Decimal("100")))
    db.add(DispatchDriverAssignment(dispatch_id=completed_dispatch.id, driver_user_id=driver.id, assigned_by_user_id=farmer_a.id, vehicle_registration="AP16-DEMO-03", tracking_mode="simulated", sharing_status="arrived", started_at=datetime.now(timezone.utc)-timedelta(hours=2), stopped_at=datetime.now(timezone.utc)-timedelta(hours=1), arrived_at=datetime.now(timezone.utc)-timedelta(hours=1)))
    completed_receipt = Receipt(order_id=completed_order.id, recorded_by_user_id=buyer.id, note="Full sample receipt accepted")
    db.add(completed_receipt); db.flush(); db.add(ReceiptLine(receipt_id=completed_receipt.id, order_line_id=completed_line.id, quantity_kg=Decimal("100"), deduction_paise=0, deduction_reason=""))
    db.add_all([
        TrackingEvent(order_id=completed_order.id, actor_user_id=farmer_a.id, status="in_transit", note="Sample consignment dispatched."),
        TrackingEvent(order_id=completed_order.id, actor_user_id=buyer.id, status="delivered", note="Full quantity received."),
    ])

    db.add(OutboxJob(event_key="demo.retry.recovery", event_type="demo.recovery", payload={"organization_id": str(buyer_org.id), "title": "Notification recovery demonstrated", "body": "This notification succeeded after one intentional temporary failure.", "link": "/notifications", "simulate_fail_once": True}, status="pending"))
    db.add(AuditEvent(actor_user_id=admin.id, organization_id=platform.id, action="demo.seeded", entity_type="system", details={"sample_data": True, "prices_simulated": True}))


def main():
    parser = argparse.ArgumentParser(description="Seed fictional AgriLink demo data")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--confirm-demo-reset", action="store_true")
    parser.add_argument("--repair-demo-accounts", action="store_true")
    parser.add_argument("--confirm-demo-repair", action="store_true")
    parser.add_argument("--seed-demo", action="store_true")
    parser.add_argument("--confirm-demo-seed", action="store_true")
    parser.add_argument("--ensure-tracking-demo", action="store_true")
    parser.add_argument("--confirm-demo-tracking", action="store_true")
    args = parser.parse_args()
    app = create_app()
    with app.app_context(), session_scope(app) as db:
        if args.ensure_tracking_demo:
            if not demo_mode_enabled() or not args.confirm_demo_tracking:
                raise SystemExit("Tracking demo setup refused. Enable DEMO_MODE and pass --confirm-demo-tracking.")
            drivers, assignments = ensure_tracking_demo(db)
            print(f"Tracking demo ready: {drivers} drivers, {assignments} existing dispatches assigned.")
            return
        if args.repair_demo_accounts:
            if not demo_mode_enabled() or not args.confirm_demo_repair:
                raise SystemExit("Repair refused. Enable DEMO_MODE and pass --confirm-demo-repair.")
            repaired = repair_demo_accounts(db)
            print(f"Repaired {repaired} demo accounts and revoked their existing sessions.")
            return
        if args.reset:
            if not demo_mode_enabled() or not args.confirm_demo_reset:
                raise SystemExit("Reset refused. Enable DEMO_MODE and pass --confirm-demo-reset.")
            names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
            db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        elif not args.repair_demo_accounts and (not args.seed_demo or not args.confirm_demo_seed or not demo_mode_enabled()):
            raise SystemExit("Seed refused. Enable DEMO_MODE and pass --seed-demo --confirm-demo-seed.")
        if db.query(User).first():
            print("Database already contains users; no seed changes made.")
            return
        seed(db)
    print("Demo data created. Password for every @agrilink.demo account: " + DEMO_PASSWORD)


if __name__ == "__main__":
    main()
