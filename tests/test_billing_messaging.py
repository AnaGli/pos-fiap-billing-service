import os

os.environ["DATABASE_URL"] = "sqlite:///./test_billing_service.db"
os.environ["RABBITMQ_URL"] = "amqp://guest:guest@localhost:5672/"

import json

import pytest

from app.database import Base, SessionLocal, engine
from app.events.handlers import handle_event
from app.messaging import consumer
from app.messaging.outbox_publisher import publish_pending_events
from app.messaging.rabbitmq import RabbitMQPublisher, declare_topology, rabbitmq_url, routing_key_for
from app.messaging.topology import EXCHANGE_NAME, QUEUE_BINDINGS, QueueBinding
from app.models.billing import Budget, BudgetStatus, Payment, PaymentStatus
from app.models.outbox_event import OutboxEvent


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_rabbitmq_url_reads_env():
    assert rabbitmq_url() == "amqp://guest:guest@localhost:5672/"


def test_routing_key_for_converts_camel_case():
    assert routing_key_for("PaymentApproved") == "payment.approved"
    assert routing_key_for("ExecutionFailed") == "execution.failed"


def test_declare_topology_declares_exchange_and_bindings():
    calls = []

    class FakeChannel:
        def exchange_declare(self, **kwargs):
            calls.append(("exchange", kwargs))

        def queue_declare(self, **kwargs):
            calls.append(("queue", kwargs))

        def queue_bind(self, **kwargs):
            calls.append(("bind", kwargs))

    channel = FakeChannel()
    bindings = [QueueBinding("billing.test", "billing.test.key")]

    declare_topology(channel, bindings)

    assert calls[0] == ("exchange", {"exchange": EXCHANGE_NAME, "exchange_type": "topic", "durable": True})
    assert ("queue", {"queue": "billing.test", "durable": True}) in calls
    assert ("bind", {"exchange": EXCHANGE_NAME, "queue": "billing.test", "routing_key": "billing.test.key"}) in calls


def test_handle_event_raises_for_unsupported_event():
    with SessionLocal() as db, pytest.raises(ValueError):
        handle_event(db, {"eventType": "UnknownEvent"})


def test_handle_event_execution_failed_triggers_refund():
    with SessionLocal() as db:
        budget = Budget(order_id=444, total_amount=55.0, status=BudgetStatus.PAID)
        budget.payments.append(
            Payment(provider="MERCADO_PAGO", provider_reference="mp-444", amount=55.0, status=PaymentStatus.APPROVED)
        )
        db.add(budget)
        db.commit()

        updated = handle_event(
            db,
            {"eventType": "ExecutionFailed", "orderId": 444, "reason": "Falha de execução"},
        )

        assert updated.status == BudgetStatus.REFUNDED


def test_publish_pending_events_marks_event_as_published(monkeypatch):
    published_messages = []

    class FakePublisher:
        def publish(self, event_type, message):
            published_messages.append((event_type, message))

    monkeypatch.setattr("app.messaging.outbox_publisher.RabbitMQPublisher", lambda: FakePublisher())

    with SessionLocal() as db:
        event = OutboxEvent(
            event_type="BudgetCreated",
            aggregate_id="101",
            payload={"orderId": 101, "budgetId": 1, "totalAmount": 155.0},
        )
        db.add(event)
        db.commit()

    count = publish_pending_events()

    assert count == 1
    assert published_messages[0][0] == "BudgetCreated"
    assert published_messages[0][1]["eventType"] == "BudgetCreated"

    with SessionLocal() as db:
        persisted = db.query(OutboxEvent).one()
        assert persisted.published_at is not None


def test_rabbitmq_publisher_uses_expected_routing_key(monkeypatch):
    published = {}

    class FakeChannel:
        def confirm_delivery(self):
            published["confirmed"] = True

        def basic_publish(self, **kwargs):
            published.update(kwargs)

    class FakeConnection:
        def __init__(self):
            self.channel_instance = FakeChannel()

        def channel(self):
            return self.channel_instance

        def close(self):
            published["closed"] = True

    monkeypatch.setattr("app.messaging.rabbitmq.build_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.messaging.rabbitmq.declare_topology", lambda channel, bindings: None)

    RabbitMQPublisher().publish("PaymentApproved", {"orderId": 1})

    assert published["exchange"] == EXCHANGE_NAME
    assert published["routing_key"] == "payment.approved"
    assert json.loads(published["body"]) == {"orderId": 1}
    assert published["mandatory"] is True
    assert published["closed"] is True


def test_queue_bindings_cover_expected_event_routes():
    assert ("billing.diagnosis-completed", "diagnosis.completed") in {(b.queue_name, b.routing_key) for b in QUEUE_BINDINGS}
    assert ("billing.execution-failed", "execution.failed") in {(b.queue_name, b.routing_key) for b in QUEUE_BINDINGS}


def test_consumer_main_processes_message_and_acknowledges(monkeypatch):
    consumed = {}

    class FakeMethod:
        delivery_tag = "tag-1"

    class FakeChannel:
        def basic_qos(self, prefetch_count):
            consumed["prefetch_count"] = prefetch_count

        def basic_consume(self, queue, on_message_callback):
            consumed.setdefault("queues", []).append(queue)
            consumed["callback"] = on_message_callback

        def start_consuming(self):
            consumed["started"] = True
            consumed["callback"](
                self,
                FakeMethod(),
                None,
                json.dumps({"eventType": "DiagnosisCompleted", "orderId": 123}).encode(),
            )

        def basic_ack(self, delivery_tag):
            consumed["ack"] = delivery_tag

        def basic_nack(self, delivery_tag, requeue):
            consumed["nack"] = (delivery_tag, requeue)

    class FakeConnection:
        def __init__(self):
            self.channel_instance = FakeChannel()

        def channel(self):
            return self.channel_instance

    monkeypatch.setattr("app.messaging.consumer.build_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.messaging.consumer.declare_topology", lambda channel, bindings: None)
    monkeypatch.setattr("app.messaging.consumer.handle_event", lambda db, event: consumed.setdefault("event", event))

    consumer.main()

    assert consumed["prefetch_count"] == 10
    assert set(consumed["queues"]) == {binding.queue_name for binding in QUEUE_BINDINGS}
    assert consumed["started"] is True
    assert consumed["event"] == {"eventType": "DiagnosisCompleted", "orderId": 123}
    assert consumed["ack"] == "tag-1"
    assert "nack" not in consumed


def test_consumer_main_requeues_message_on_processing_error(monkeypatch):
    consumed = {}

    class FakeMethod:
        delivery_tag = "tag-2"

    class FakeChannel:
        def basic_qos(self, prefetch_count):
            consumed["prefetch_count"] = prefetch_count

        def basic_consume(self, queue, on_message_callback):
            consumed["callback"] = on_message_callback

        def start_consuming(self):
            consumed["callback"](
                self,
                FakeMethod(),
                None,
                json.dumps({"eventType": "DiagnosisCompleted", "orderId": 456}).encode(),
            )

        def basic_ack(self, delivery_tag):
            consumed["ack"] = delivery_tag

        def basic_nack(self, delivery_tag, requeue):
            consumed["nack"] = (delivery_tag, requeue)

    class FakeConnection:
        def __init__(self):
            self.channel_instance = FakeChannel()

        def channel(self):
            return self.channel_instance

    monkeypatch.setattr("app.messaging.consumer.build_connection", lambda: FakeConnection())
    monkeypatch.setattr("app.messaging.consumer.declare_topology", lambda channel, bindings: None)

    def raise_error(db, event):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.messaging.consumer.handle_event", raise_error)

    consumer.main()

    assert consumed["nack"] == ("tag-2", True)
    assert "ack" not in consumed
