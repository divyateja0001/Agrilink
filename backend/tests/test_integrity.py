from datetime import datetime, timezone

import pytest

from app.db import session_scope
from app.models import OutboxJob, User
from app.services.orders import DomainError, begin_idempotent
from app.services.outbox import process_one


def test_idempotency_replay_and_conflicting_payload(app):
    with app.app_context(), session_scope(app) as db:
        user=User(email="idem@example.com",full_name="Idem",password_hash="x");db.add(user);db.flush()
        record,prior=begin_idempotent(db,user.id,"receipt","same-key",{"quantity":10});assert prior is None
        record.response_body={"receipt_id":"one"};db.flush()
        _,prior=begin_idempotent(db,user.id,"receipt","same-key",{"quantity":10});assert prior=={"receipt_id":"one"}
        with pytest.raises(DomainError) as error: begin_idempotent(db,user.id,"receipt","same-key",{"quantity":11})
        assert error.value.status==409


def test_outbox_recovers_from_one_failure_without_duplicate_effect(app):
    with app.app_context(), session_scope(app) as db:
        job=OutboxJob(event_key="test-fail-once",event_type="test",payload={"simulate_fail_once":True,"user_ids":[]});db.add(job);db.flush()
        assert process_one(db);assert job.status=="retry";assert job.attempts==1
        job.available_at=datetime.now(timezone.utc);db.flush()
        assert process_one(db);assert job.status=="completed";assert job.attempts==2
