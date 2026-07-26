import json
import logging

from app.database import SessionLocal
from app.events.handlers import handle_event
from app.messaging.rabbitmq import build_connection, declare_topology
from app.messaging.topology import QUEUE_BINDINGS

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    connection = build_connection()
    channel = connection.channel()
    declare_topology(channel, QUEUE_BINDINGS)
    channel.basic_qos(prefetch_count=10)

    def callback(ch, method, properties, body):
        try:
            event = json.loads(body)
            with SessionLocal() as db:
                handle_event(db, event)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception("Failed to process Billing event")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    for binding in QUEUE_BINDINGS:
        channel.basic_consume(queue=binding.queue_name, on_message_callback=callback)

    logger.info("Billing consumer listening on %s", [binding.queue_name for binding in QUEUE_BINDINGS])
    channel.start_consuming()


if __name__ == "__main__":
    main()
