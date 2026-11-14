"""Database and actor helpers for the demo workspace."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, Request, status
from .mcp_database import MCPCollection as Collection, MCPDatabase as Database

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


async def _upsert_by_key(collection: Collection, key: dict, insert_fields: dict) -> dict:
    return await collection.upsert(key, insert_fields)


async def ensure_demo_profile(database: Database) -> tuple[ObjectId, ObjectId]:
    user_key = {"email": DEMO_USER_EMAIL}
    user = await database.users.find_one(user_key)
    if user is not None:
        return await _linked_demo_customer(database, user)

    now = datetime.now(timezone.utc)
    customer = await _upsert_by_key(
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
    user = await _upsert_by_key(
        database["users"],
        user_key,
        {
            "created_at": now,
            "updated_at": now,
            "name": "Customer 360 Demo User",
            "email": DEMO_USER_EMAIL,
            "role": "customer",
            "customer_id": customer["_id"],
        },
    )
    return await _linked_demo_customer(database, user)


async def _linked_demo_customer(database: Database, user: dict) -> tuple[ObjectId, ObjectId]:
    customer_id = user.get("customer_id")
    if (
        user.get("role") != "customer"
        or not isinstance(customer_id, ObjectId)
        or await database.customers.find_one({"_id": customer_id}) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The demo user does not have a valid customer profile.",
        )
    return customer_id, user["_id"]


def object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status_code=404, detail="Record not found.") from None


async def get_actor(database: Database, role: str, actor_id: str | None) -> ObjectId:
    query = {"role": role}
    if actor_id is not None:
        query["_id"] = object_id(actor_id)
    actor = await database.users.find_one(query)
    if actor is None:
        raise HTTPException(status_code=404, detail="Demo persona not found.")
    return actor["_id"]


async def conversation_actor(database: Database, customer_id: str | None) -> tuple[ObjectId, ObjectId]:
    if customer_id is None:
        return await ensure_demo_profile(database)
    customer = object_id(customer_id)
    user = await database.users.find_one({"role": "customer", "customer_id": customer})
    if user is None:
        raise HTTPException(status_code=404, detail="Demo customer not found.")
    return customer, user["_id"]


def customer_scope(customer_id: ObjectId) -> dict:
    return {"$or": [
        {"owner_customer_id": customer_id},
        {"owner_customer_id": {"$exists": False}, "customer_id": customer_id},
    ]}
