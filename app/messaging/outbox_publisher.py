import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.messaging.rabbitmq import RabbitMQPublisher
from app.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)


def publish_pending_events() -> int:
    publisher = RabbitMQPublisher()
    published = 0
    with SessionLocal() as db:
        events = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            publisher.publish(
                event.event_type,
                {
                    **event.payload,
                    "eventId": str(event.id),
                    "eventType": event.event_type,
                    "occurredAt": event.created_at.isoformat(),
                },
            )
            event.published_at = datetime.now(timezone.utc)
            published += 1
        db.commit()
    return published


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            count = publish_pending_events()
            if count:
                logger.info("Published %s Billing event(s)", count)
        except Exception:
            logger.exception("Billing outbox publish failed; retrying")
        time.sleep(2)


if __name__ == "__main__":
    main()
