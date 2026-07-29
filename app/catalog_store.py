import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

import boto3
from botocore.exceptions import ClientError

from app.models.billing import CatalogItemType


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CatalogItemDocument:
    code: str
    name: str
    item_type: CatalogItemType
    price: float
    active: bool = True


class CatalogStore(Protocol):
    def create_item(self, item: CatalogItemDocument) -> CatalogItemDocument: ...

    def get_item_by_code(self, code: str) -> CatalogItemDocument | None: ...

    def list_items(self) -> list[CatalogItemDocument]: ...

    def reset(self) -> None: ...


class InMemoryCatalogStore:
    def __init__(self):
        self._items: dict[str, CatalogItemDocument] = {}

    def create_item(self, item: CatalogItemDocument) -> CatalogItemDocument:
        if item.code in self._items:
            raise ValueError("Catalog item already exists")
        self._items[item.code] = item
        return item

    def get_item_by_code(self, code: str) -> CatalogItemDocument | None:
        return self._items.get(code)

    def list_items(self) -> list[CatalogItemDocument]:
        return [self._items[key] for key in sorted(self._items.keys())]

    def reset(self) -> None:
        self._items.clear()


class DynamoDBCatalogStore:
    def __init__(self):
        self.table_name = os.getenv("DYNAMODB_TABLE_NAME", "billing_catalog")
        self.region_name = os.getenv("AWS_REGION", "us-east-1")
        endpoint_url = os.getenv("DYNAMODB_ENDPOINT_URL") or None
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "dummy")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy")
        self._dynamodb = boto3.resource(
            "dynamodb",
            region_name=self.region_name,
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        self._table = self._dynamodb.Table(self.table_name)
        self._ensure_table_exists()

    def _ensure_table_exists(self) -> None:
        existing_tables = self._dynamodb.meta.client.list_tables()["TableNames"]
        if self.table_name in existing_tables:
            return

        table = self._dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        self._table = table

    def _pk(self, code: str) -> str:
        return f"ITEM#{code}"

    def create_item(self, item: CatalogItemDocument) -> CatalogItemDocument:
        payload = {
            "pk": self._pk(item.code),
            "code": item.code,
            "name": item.name,
            "item_type": item.item_type.value,
            "price": Decimal(str(item.price)),
            "active": item.active,
            "updated_at": utcnow_iso(),
        }
        try:
            self._table.put_item(Item=payload, ConditionExpression="attribute_not_exists(pk)")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ValueError("Catalog item already exists") from exc
            raise
        return item

    def get_item_by_code(self, code: str) -> CatalogItemDocument | None:
        response = self._table.get_item(Key={"pk": self._pk(code)})
        item = response.get("Item")
        if item is None:
            return None
        return CatalogItemDocument(
            code=item["code"],
            name=item["name"],
            item_type=CatalogItemType(item["item_type"]),
            price=float(item["price"]),
            active=bool(item.get("active", True)),
        )

    def list_items(self) -> list[CatalogItemDocument]:
        response = self._table.scan()
        items = response.get("Items", [])
        documents = [
            CatalogItemDocument(
                code=item["code"],
                name=item["name"],
                item_type=CatalogItemType(item["item_type"]),
                price=float(item["price"]),
                active=bool(item.get("active", True)),
            )
            for item in items
        ]
        return sorted(documents, key=lambda item: item.code)

    def reset(self) -> None:
        items = self._table.scan().get("Items", [])
        with self._table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"pk": item["pk"]})


_memory_store = InMemoryCatalogStore()
_dynamodb_store: DynamoDBCatalogStore | None = None


def get_catalog_store() -> CatalogStore:
    global _dynamodb_store
    backend = os.getenv("CATALOG_BACKEND", "dynamodb").lower()
    if backend == "memory":
        return _memory_store
    if _dynamodb_store is None:
        _dynamodb_store = DynamoDBCatalogStore()
    return _dynamodb_store


def reset_catalog_store() -> None:
    global _dynamodb_store
    backend = os.getenv("CATALOG_BACKEND", "dynamodb").lower()
    if backend == "memory":
        _memory_store.reset()
    elif _dynamodb_store is not None:
        _dynamodb_store.reset()
