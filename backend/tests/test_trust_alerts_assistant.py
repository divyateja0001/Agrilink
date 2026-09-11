from datetime import date, timedelta
from unittest.mock import patch
import hashlib
import hmac
import uuid

from sqlalchemy import select

from app.db import session_scope
from app.models import Notification, NotificationDelivery, Order, Organization, PushSubscription
from app.services.outbox import enqueue, process_one, process_push_delivery
from test_negotiations import marketplace_story, mutation, register


def complete_marketplace_order(app):
    buyer, farmer, outsider, buyer_csrf, farmer_csrf, outsider_csrf, requirement, _, quote = marketplace_story(app)
    confirmed = mutation(
        buyer,
        f"/api/requirements/{requirement['id']}/confirm",
        buyer_csrf,
        {"quotation_ids": [quote["id"]]},
        **{"Idempotency-Key": "review-order-confirm"},
    )
    assert confirmed.status_code == 201
    order_id = confirmed.json["orders"][0]["order_id"]
    line = farmer.get(f"/api/orders/{order_id}").json["lines"][0]
    dispatched = mutation(
        farmer,
        f"/api/orders/{order_id}/dispatches",
        farmer_csrf,
        {"lines": [{"order_line_id": line["id"], "quantity_kg": line["agreed_quantity_kg"]}], "reference": "REVIEW-DISPATCH"},
        **{"Idempotency-Key": "review-order-dispatch"},
    )
    assert dispatched.status_code == 201
    received = mutation(
        buyer,
        f"/api/orders/{order_id}/receipts",
        buyer_csrf,
        {"lines": [{"order_line_id": line["id"], "quantity_kg": line["agreed_quantity_kg"], "deduction_paise": 0}], "note": "Complete receipt"},
        **{"Idempotency-Key": "review-order-receipt"},
    )
    assert received.status_code == 201 and received.json["status"] == "received"
    return buyer, farmer, outsider, buyer_csrf, farmer_csrf, outsider_csrf, order_id


def review_body(supplier_id, *, version=None, score=5):
    body = {
        "supplier_id": supplier_id,
        "reviewed_role": "supplier",
        "overall_rating": score,
        "quality_rating": score,
        "delivery_rating": score,
        "communication_rating": score,
        "comment": "Reliable produce and clear communication.",
    }
    if version is not None:
        body["version"] = version
    return {"reviews": [body]}


def test_razorpay_test_checkout_creates_order_verifies_signature_and_captures_authorized_payment(app):
    buyer, _, _, buyer_csrf, _, _, order_id = complete_marketplace_order(app)
    app.config.update(RAZORPAY_ENABLED=True, RAZORPAY_KEY_ID="rzp_test_agrilink", RAZORPAY_KEY_SECRET="test-secret")

    provider_state = {"amount": 0}

    def provider(method, path, body=None):
        if method == "POST" and path == "/orders":
            provider_state["amount"] = body["amount"]
            return {"id": "order_test_agrilink", "amount": body["amount"], "currency": "INR"}
        if method == "GET" and path == "/payments/pay_test_agrilink":
            return {"id": "pay_test_agrilink", "order_id": "order_test_agrilink", "amount": provider_state["amount"], "currency": "INR", "status": "authorized"}
        if method == "POST" and path == "/payments/pay_test_agrilink/capture":
            assert body == {"amount": provider_state["amount"], "currency": "INR"}
            return {"id": "pay_test_agrilink", "order_id": "order_test_agrilink", "amount": provider_state["amount"], "currency": "INR", "status": "captured"}
        raise AssertionError(f"Unexpected provider request: {method} {path}")

    with patch("app.routes.orders._razorpay_request", side_effect=provider):
        config = buyer.get("/api/payments/config")
        assert config.status_code == 200 and config.json["enabled"] is True and config.json["test_mode"] is True
        created = mutation(buyer, f"/api/orders/{order_id}/razorpay-order", buyer_csrf, {})
        assert created.status_code == 201
        replayed = mutation(buyer, f"/api/orders/{order_id}/razorpay-order", buyer_csrf, {})
        assert replayed.status_code == 200
        assert replayed.json["razorpay_order_id"] == created.json["razorpay_order_id"]
        assert replayed.json["idempotent_replay"] is True
        signature = hmac.new(b"test-secret", b"order_test_agrilink|pay_test_agrilink", hashlib.sha256).hexdigest()
        verified = mutation(
            buyer,
            f"/api/orders/{order_id}/razorpay-verify",
            buyer_csrf,
            {"razorpay_order_id": "order_test_agrilink", "razorpay_payment_id": "pay_test_agrilink", "razorpay_signature": signature},
        )
        assert verified.status_code == 200
        assert verified.json["payment_status"] == "paid"


def test_completed_order_review_is_unique_editable_and_anonymous(app):
    buyer, farmer, outsider, buyer_csrf, _, _, order_id = complete_marketplace_order(app)
    order = buyer.get(f"/api/orders/{order_id}").json
    supplier_id = order["supplier_organization_id"]
    assert order["review_eligible"] is True

    invalid = mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, review_body(supplier_id, score=6))
    assert invalid.status_code == 422
    created = mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, review_body(supplier_id))
    assert created.status_code == 201
    created_review = created.json["items"][0]
    assert created_review["overall_rating"] == 5

    duplicate = mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, review_body(supplier_id))
    assert duplicate.status_code == 409 and duplicate.json["error"] == "duplicate_review"

    stale = buyer.patch(
        f"/api/orders/{order_id}/reviews",
        json=review_body(supplier_id, version=0, score=4),
        headers={"X-CSRF-Token": buyer_csrf},
    )
    assert stale.status_code == 409 and stale.json["error"] == "stale_update"
    updated = buyer.patch(
        f"/api/orders/{order_id}/reviews",
        json=review_body(supplier_id, version=created_review["version"], score=4),
        headers={"X-CSRF-Token": buyer_csrf},
    )
    assert updated.status_code == 200 and updated.json["items"][0]["overall_rating"] == 4

    public = outsider.get(f"/api/organizations/{supplier_id}/reviews")
    assert public.status_code == 200
    assert public.json["summary"]["average_rating"] == 4
    assert public.json["items"][0]["buyer_label"] == "Verified buyer"
    assert "buyer_organization_id" not in public.json["items"][0]
    assert farmer.get(f"/api/orders/{order_id}").status_code == 200
    assert outsider.get(f"/api/orders/{order_id}").status_code == 403


def test_review_rejected_before_full_receipt_and_validates_dimensions(app):
    buyer, _, _, buyer_csrf, _, _, requirement, _, quote = marketplace_story(app)
    confirmed = mutation(buyer, f"/api/requirements/{requirement['id']}/confirm", buyer_csrf, {"quotation_ids": [quote["id"]]}, **{"Idempotency-Key": "early-review-confirm"})
    order_id = confirmed.json["orders"][0]["order_id"]
    supplier_id = buyer.get(f"/api/orders/{order_id}").json["supplier_organization_id"]
    early = mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, review_body(supplier_id))
    assert early.status_code == 409 and early.json["error"] == "invalid_status"
    invalid = review_body(supplier_id, score=6)
    assert mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, invalid).status_code == 409


def test_fpo_coordinated_order_reviews_farmer_and_fpo_atomically(app):
    buyer, _, _, buyer_csrf, _, _, order_id = complete_marketplace_order(app)
    with app.app_context(), session_scope(app) as db:
        order = db.get(Order, uuid.UUID(order_id))
        fpo = Organization(name="Review Coordination FPO", org_type="fpo", location="Guntur")
        db.add(fpo); db.flush(); order.coordinating_fpo_id = fpo.id
        supplier_id = str(order.supplier_organization_id); fpo_id = str(fpo.id)

    only_farmer = mutation(buyer, f"/api/orders/{order_id}/reviews", buyer_csrf, review_body(supplier_id))
    assert only_farmer.status_code == 422
    combined = mutation(
        buyer,
        f"/api/orders/{order_id}/reviews",
        buyer_csrf,
        {"reviews": [review_body(supplier_id)["reviews"][0], {**review_body(fpo_id)["reviews"][0], "reviewed_role": "fpo", "overall_rating": 4}]},
    )
    assert combined.status_code == 201
    assert {(item["supplier_id"], item["reviewed_role"]) for item in combined.json["items"]} == {(supplier_id, "supplier"), (fpo_id, "fpo")}


def _drain_outbox(app):
    with app.app_context(), session_scope(app) as db:
        for _ in range(100):
            if not process_one(db):
                break
            db.flush()


def test_compatible_supply_and_demand_create_targeted_notifications(app):
    buyer, farmer, _, buyer_csrf, _, _, _, _, _ = marketplace_story(app)
    deadline = (date.today() + timedelta(days=8)).isoformat()
    next_requirement = mutation(
        buyer,
        "/api/requirements",
        buyer_csrf,
        {"crop": "Tomato", "variety": "Arka Rakshak", "quantity_kg": 50, "acceptable_quality": "B", "destination": "Vijayawada", "delivery_mode": "buyer_pickup", "delivery_deadline": deadline, "budget_price_inr": 26, "notes": "Matched alert"},
    )
    assert next_requirement.status_code == 201 and next_requirement.json["notified_users"] >= 1
    _drain_outbox(app)

    buyer_alerts = buyer.get("/api/notifications").json["items"]
    farmer_alerts = farmer.get("/api/notifications").json["items"]
    assert any("supply" in item["title"].lower() for item in buyer_alerts)
    assert any("requirement" in item["title"].lower() for item in farmer_alerts)


def test_push_delivery_is_created_once_and_sent_once(app):
    client = app.test_client()
    csrf = register(client, email="push@example.com", role="buyer", organization="Push Buyer")
    user_id = client.get("/api/auth/session").json["user"]["id"]
    subscription = mutation(
        client,
        "/api/push/subscriptions",
        csrf,
        {"endpoint": "https://push.example.test/subscription-one", "keys": {"p256dh": "p" * 80, "auth": "a" * 24}},
    )
    assert subscription.status_code == 201
    with app.app_context(), session_scope(app) as db:
        enqueue(db, "test.push", {"user_ids": [user_id], "title": "Matched requirement", "body": "A buyer needs your crop.", "link": "/requirements"}, "push-once")
        db.flush()
        assert process_one(db)
        db.flush()
        assert db.scalar(select(Notification).where(Notification.event_key == "push-once"))
        assert len(list(db.scalars(select(NotificationDelivery)))) == 1
        with patch("pywebpush.webpush") as send:
            assert process_push_delivery(db, {"PUSH_ENABLED": True, "VAPID_PRIVATE_KEY": "private", "VAPID_SUBJECT": "mailto:test@example.com"})
            db.flush()
            assert send.call_count == 1
            assert not process_push_delivery(db, {"PUSH_ENABLED": True, "VAPID_PRIVATE_KEY": "private", "VAPID_SUBJECT": "mailto:test@example.com"})
        assert len(list(db.scalars(select(PushSubscription)))) == 1


def test_assistant_conversations_persist_reset_and_stay_private(app):
    buyer = app.test_client(); farmer = app.test_client()
    buyer_csrf = register(buyer, email="assistant-buyer@example.com", role="buyer", organization="Assistant Buyer")
    register(farmer, email="assistant-farmer@example.com", role="farmer", organization="Assistant Farm")
    app.config["AI_ENABLED"] = False
    app.config["MISTRAL_API_KEY"] = ""

    created = mutation(buyer, "/api/assistant/conversations", buyer_csrf, {"language": "te"})
    assert created.status_code == 201 and created.json["role"] == "buyer"
    conversation_id = created.json["id"]
    assert farmer.get(f"/api/assistant/conversations/{conversation_id}/messages").status_code == 404

    reply = mutation(
        buyer,
        f"/api/assistant/conversations/{conversation_id}/messages",
        buyer_csrf,
        {"message": "నాకు టమాటాలు కొనాలి", "mode": "general", "language": "te"},
    )
    assert reply.status_code == 201
    assert reply.json["message"]["source"] == "rule_based"
    history = buyer.get(f"/api/assistant/conversations/{conversation_id}/messages")
    assert history.status_code == 200 and len(history.json["items"]) == 2

    reset = mutation(buyer, f"/api/assistant/conversations/{conversation_id}/reset", buyer_csrf, {})
    assert reset.status_code == 201 and reset.json["id"] != conversation_id
    assert buyer.get(f"/api/assistant/conversations/{conversation_id}/messages").status_code == 404
