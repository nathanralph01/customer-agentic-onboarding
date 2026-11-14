import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from bson import ObjectId
from fastapi import HTTPException

from app.main import discard_draft


class DiscardDraftTest(unittest.IsolatedAsyncioTestCase):
    async def test_discard_only_deletes_current_draft_and_its_progress(self):
        owner = ObjectId()
        onboarding = ObjectId()
        document = {"_id": ObjectId(), "storage_id": ObjectId()}
        conversation = {"_id": ObjectId(), "onboarding_id": onboarding, "customer_id": owner}
        db = SimpleNamespace(
            conversations=AsyncMock(), onboardings=AsyncMock(), documents=AsyncMock(),
            users=AsyncMock(), customers=AsyncMock(), call=AsyncMock(),
        )
        db.conversations.find_one.return_value = conversation
        db.documents.find.return_value = [document]
        db.onboardings.find_one.return_value = {"status": "APPLIED"}
        request = SimpleNamespace(query_params={"customer_id": str(owner)})
        with (
            patch("app.main.get_database", return_value=db),
            patch("app.main.conversation_actor", new=AsyncMock(return_value=(owner, ObjectId()))),
            patch("app.main.MCPBucket") as bucket,
        ):
            bucket.return_value.delete = AsyncMock()
            with self.assertRaises(HTTPException) as error:
                await discard_draft(uuid4(), request)
            self.assertEqual(error.exception.status_code, 409)
            db.call.assert_not_awaited()

            db.onboardings.find_one.return_value = {"status": "DRAFT"}
            self.assertEqual(await discard_draft(uuid4(), request), {"deleted": True})
            bucket.return_value.delete.assert_awaited_once_with(document["storage_id"], missing_ok=True)
        db.call.assert_awaited_once_with("delete-many", "messages", filter={"conversation_id": conversation["_id"]})
        db.onboardings.delete_one.assert_awaited_once_with({"_id": onboarding, "status": "DRAFT"})
        db.conversations.delete_one.assert_awaited_once_with({"_id": conversation["_id"]})
        db.customers.delete_one.assert_not_awaited()
