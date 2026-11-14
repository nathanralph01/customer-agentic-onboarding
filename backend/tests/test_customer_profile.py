import unittest
from unittest.mock import AsyncMock, patch
from bson import ObjectId
from app.main import create_business_profile, _save_answer


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_chats_get_distinct_customers_and_retries_reuse_ids(self):
        from datetime import datetime, timezone
        from uuid import uuid4
        db = {name: AsyncMock() for name in ("users", "customers")}
        async def upsert(key, fields):
            return {**key, **fields}
        for collection in db.values():
            collection.upsert.side_effect = upsert
        first, second = str(uuid4()), str(uuid4())
        now = datetime.now(timezone.utc)
        a = await create_business_profile(db, first, now)
        b = await create_business_profile(db, second, now)
        replay = await create_business_profile(db, first, now)
        self.assertNotEqual(a[0], b[0])
        self.assertNotEqual(a[1], b[1])
        self.assertEqual(a, replay)

    async def test_answers_update_profile_and_application_without_guessing(self):
        db = {name: AsyncMock() for name in ("customers", "messages", "onboardings", "conversations")}
        answers = ["MDPL Company", "Software services", "Ontario, Canada", "Alex owns 100%", "Business account"]
        db["messages"].find_one.return_value = {"content": answers[-1]}
        customer_id = ObjectId()
        conversation = {"_id": ObjectId(), "onboarding_id": ObjectId()}
        with patch("app.main._read_answers", AsyncMock(return_value=answers)):
            await _save_answer(db, conversation, customer_id, 4, answers[-1])
        profile = db["customers"].update_one.call_args.args[1]["$set"]
        self.assertEqual(profile["legal_name"], answers[0])
        self.assertEqual(profile["ownership_description"], answers[3])
        self.assertNotIn("owners", profile)
        application = db["onboardings"].update_one.call_args.args[1]["$set"]["application"]
        self.assertEqual(application["banking_needs"], answers[4])
