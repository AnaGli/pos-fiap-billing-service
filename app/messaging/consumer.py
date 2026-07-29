import json
import logging

from ddtrace import tracer

from app.core.logging_config import set_log_context
from app.core.tracing import activate_trace_from_headers, service_name
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
            headers = getattr(properties, "headers", None) if properties is not None else None
            activate_trace_from_headers(headers)
            event = json.loads(body)
            correlation_id = None if not headers else headers.get("x-correlation-id")
            if isinstance(correlation_id, bytes):
                correlation_id = correlation_id.decode()
            set_log_context(
                correlation_id=correlation_id,
                business_operation="consume_billing_event",
                order_id=event.get("orderId"),
            )
            with tracer.trace(
                "rabbitmq.consume",
                service=service_name(),
                resource=event.get("eventType", "unknown"),
                span_type="worker",
            ) as span:
                routing_key = getattr(method, "routing_key", "unknown")
                span.set_tag("span.kind", "consumer")
                span.set_tag("messaging.system", "rabbitmq")
                span.set_tag("messaging.destination", routing_key)
                span.set_tag("messaging.rabbitmq.queue", routing_key)
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
