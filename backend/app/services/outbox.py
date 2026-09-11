from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import Membership, Notification, NotificationDelivery, OutboxJob, PushSubscription


def enqueue(db, event_type: str, payload: dict, event_key: str | None = None):
    db.add(
        OutboxJob(
            event_key=event_key or f"{event_type}:{uuid.uuid4()}",
            event_type=event_type,
            payload=payload,
        )
    )


def recipients_for_org(db, organization_id):
    return list(db.scalars(select(Membership.user_id).where(
        Membership.organization_id == organization_id,
        Membership.is_active.is_(True),
    )))


def process_one(db) -> bool:
    now = datetime.now(timezone.utc)
    job = db.scalar(
        select(OutboxJob)
        .where(OutboxJob.status.in_(["pending", "retry"]), OutboxJob.available_at <= now)
        .order_by(OutboxJob.created_at)
        .with_for_update(skip_locked=True)
    )
    if not job:
        return False
    job.status = "processing"
    job.locked_at = now
    job.attempts += 1
    try:
        if job.payload.get("simulate_fail_once") and job.attempts == 1:
            raise RuntimeError("Intentional first-attempt demo failure")
        user_ids = job.payload.get("user_ids", [])
        if job.payload.get("organization_id"):
            user_ids.extend(str(x) for x in recipients_for_org(db, job.payload["organization_id"]))
        for user_id in sorted(set(user_ids)):
            notification = db.scalar(select(Notification).where(
                Notification.user_id == user_id,
                Notification.event_key == job.event_key,
            ))
            if not notification:
                notification = Notification(
                    user_id=user_id,
                    event_key=job.event_key,
                    title=job.payload.get("title", "AgriLink update"),
                    body=job.payload.get("body", "A marketplace record was updated."),
                    link=job.payload.get("link"),
                )
                db.add(notification); db.flush()
            for subscription in db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id, PushSubscription.is_active.is_(True))):
                if not db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.notification_id == notification.id, NotificationDelivery.subscription_id == subscription.id)):
                    db.add(NotificationDelivery(notification_id=notification.id, subscription_id=subscription.id))
        job.status = "completed"
        job.last_error = None
    except Exception as exc:
        job.last_error = str(exc)[:500]
        if job.attempts >= 5:
            job.status = "exhausted"
        else:
            job.status = "retry"
            job.available_at = now + timedelta(seconds=min(60, 2 ** job.attempts))
    return True


def process_push_delivery(db, config) -> bool:
    now = datetime.now(timezone.utc)
    delivery = db.scalar(
        select(NotificationDelivery)
        .where(NotificationDelivery.status.in_(["pending", "retry"]), NotificationDelivery.available_at <= now)
        .order_by(NotificationDelivery.created_at)
        .with_for_update(skip_locked=True)
    )
    if not delivery:
        return False
    subscription = db.get(PushSubscription, delivery.subscription_id)
    notification = db.get(Notification, delivery.notification_id)
    if not subscription or not subscription.is_active or not notification:
        delivery.status = "cancelled"
        return True
    if not config.get("PUSH_ENABLED") or not config.get("VAPID_PRIVATE_KEY"):
        delivery.status = "disabled"
        delivery.last_error = "Browser push is not configured; in-app notification remains available."
        return True
    delivery.status = "processing"; delivery.attempts += 1
    try:
        import json
        from pywebpush import webpush
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps({"title": notification.title, "body": notification.body, "link": notification.link or "/notifications", "notification_id": str(notification.id)}),
            vapid_private_key=config["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": config["VAPID_SUBJECT"]},
            ttl=600,
            timeout=10,
        )
        delivery.status = "sent"; delivery.sent_at = now; delivery.last_error = None
        subscription.failure_count = 0; subscription.last_success_at = now
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        delivery.last_error = f"{type(exc).__name__}: {exc}"[:500]
        subscription.failure_count += 1
        if status in {404, 410}:
            subscription.is_active = False; delivery.status = "expired"
        elif delivery.attempts >= 5:
            delivery.status = "exhausted"
        else:
            delivery.status = "retry"; delivery.available_at = now + timedelta(seconds=min(300, 2 ** delivery.attempts))
    return True
