from dataclasses import dataclass


EXCHANGE_NAME = "workshop.events"


@dataclass(frozen=True)
class QueueBinding:
    queue_name: str
    routing_key: str


QUEUE_BINDINGS = [
    QueueBinding("billing.diagnosis-completed", "diagnosis.completed"),
    QueueBinding("billing.execution-failed", "execution.failed"),
]
