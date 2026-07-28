import json
import os

import pika

from app.core.logging_config import ensure_correlation_id
from app.core.tracing import activate_trace_from_headers, inject_trace_headers, service_name, tracer
from app.messaging.topology import EXCHANGE_NAME, QueueBinding


def rabbitmq_url() -> str:
    return os.environ["RABBITMQ_URL"]


def build_connection() -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(rabbitmq_url()))


def routing_key_for(event_type: str) -> str:
    chunks: list[str] = []
    current = ""
    for character in event_type:
        if character.isupper() and current:
            chunks.append(current.lower())
            current = character
        else:
            current += character
    if current:
        chunks.append(current.lower())
    return ".".join(chunks)


def declare_topology(channel: pika.adapters.blocking_connection.BlockingChannel, bindings: list[QueueBinding]) -> None:
    channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)
    for binding in bindings:
        channel.queue_declare(queue=binding.queue_name, durable=True)
        channel.queue_bind(exchange=EXCHANGE_NAME, queue=binding.queue_name, routing_key=binding.routing_key)


class RabbitMQPublisher:
    def publish(self, event_type: str, message: dict) -> None:
        connection = build_connection()
        try:
            channel = connection.channel()
            declare_topology(channel, [])
            channel.confirm_delivery()
            activate_trace_from_headers(message.get("traceHeaders"))
            trace_context = (
                tracer.trace(
                    "rabbitmq.publish",
                    service=service_name(),
                    resource=event_type,
                    span_type="worker",
                )
                if tracer is not None
                else None
            )
            publish_headers = {
                "x-correlation-id": message.get("correlationId") or ensure_correlation_id(),
                "x-event-type": event_type,
            }
            if trace_context is None:
                headers = inject_trace_headers(publish_headers)
                channel.basic_publish(
                    exchange=EXCHANGE_NAME,
                    routing_key=routing_key_for(event_type),
                    body=json.dumps(message, default=str),
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=pika.DeliveryMode.Persistent,
                        headers=headers,
                    ),
                    mandatory=True,
                )
            else:
                with trace_context:
                    current_span = tracer.current_span() if tracer is not None else None
                    if current_span is not None:
                        current_span.set_tag("span.kind", "producer")
                        current_span.set_tag("messaging.system", "rabbitmq")
                        current_span.set_tag("messaging.destination", EXCHANGE_NAME)
                        current_span.set_tag("messaging.rabbitmq.routing_key", routing_key_for(event_type))
                    headers = inject_trace_headers(publish_headers)
                    channel.basic_publish(
                        exchange=EXCHANGE_NAME,
                        routing_key=routing_key_for(event_type),
                        body=json.dumps(message, default=str),
                        properties=pika.BasicProperties(
                            content_type="application/json",
                            delivery_mode=pika.DeliveryMode.Persistent,
                            headers=headers,
                        ),
                        mandatory=True,
                    )
        finally:
            connection.close()
