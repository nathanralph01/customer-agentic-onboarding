"""Database and actor helpers for the demo workspace."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, Request, status
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

DEMO_CUSTOMER_NAME = "Northstar Test Goods Ltd."
DEMO_USER_EMAIL = "customer.demo@customer360.example"

def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Atlas is not configured. Set MONGODB_URI and MONGODB_DATABASE.",
        )
    return database


def _upsert_by_key(
    collection: Collection, key: dict, insert_fields: dict
) -> dict:
    try:
        return collection.find_one_and_update(
            key,
            {"$setOnInsert": insert_fields},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        existing = collection.find_one(key)
        if existing is None:
            raise
        return existing


def ensure_demo_profile(database: Database) -> tuple[ObjectId, ObjectId]:
    now = datetime.now(timezone.utc)
    customer = _upsert_by_key(
        database["customers"],
        {"legal_name": DEMO_CUSTOMER_NAME},
        {
            "created_at": now,
            "updated_at": now,
            "legal_name": DEMO_CUSTOMER_NAME,
            "industry": "Retail",
            "contact": {"email": "onboarding.demo@customer360.example"},
            "owners": [],
        },
    )
    user = _upsert_by_key(
        database["users"],
        {"email": DEMO_USER_EMAIL},
        {
            "created_at": now,
            "updated_at": now,
            "name": "Customer 360 Demo User",
            "email": DEMO_USER_EMAIL,
            "role": "customer",
            "customer_id": customer["_id"],
        },
    )
    if user.get("customer_id") != customer["_id"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The configured demo user is linked to a different customer.",
        )
    return customer["_id"], user["_id"]


def object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Record not found.") from None


def get_actor(database: Database, role: str, actor_id: str | None) -> ObjectId:
    query = {"role": role}
    if actor_id is not None:
        query["_id"] = object_id(actor_id)
    actor = database.users.find_one(query)
    if actor is None:
        raise HTTPException(status_code=404, detail="Demo persona not found.")
    return actor["_id"]


def conversation_actor(database: Database, customer_id: str | None) -> tuple[ObjectId, ObjectId]:
    if customer_id is None:
        return ensure_demo_profile(database)
    customer = object_id(customer_id)
    user = database.users.find_one({"role": "customer", "customer_id": customer})
    if user is None:
        raise HTTPException(status_code=404, detail="Demo customer not found.")
    return customer, user["_id"]
