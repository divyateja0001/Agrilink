from __future__ import annotations

import signal
import time

from sqlalchemy import select

from app import create_app
from app.db import session_scope
from app.models import OutboxJob
from app.services.outbox import process_one, process_push_delivery


running = True


def stop(_signum, _frame):
    global running
    running = False


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    app = create_app()
    print("AgriLink notification worker started", flush=True)
    while running:
        processed = False
        with app.app_context(), session_scope(app) as db:
            processed = process_one(db)
            if not processed:
                processed = process_push_delivery(db, app.config)
        if not processed:
            time.sleep(app.config["OUTBOX_POLL_SECONDS"])
    print("AgriLink notification worker stopped", flush=True)
