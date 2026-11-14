import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from bson import ObjectId

from app.main import ChatPayload, send_chat_message
from app.onboarding_agent import IntakeDecision
from app.workflow import now


class ChatPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_and_retry_reuse_loaded_records(self):
        owner = ObjectId()
        conversation = {
            "_id": ObjectId(), "client_id": str(uuid4()),
            "onboarding_id": ObjectId(), "customer_id": owner, "created_at": now(),
        }
        database = SimpleNamespace(conversations=AsyncMock(), onboardings=AsyncMock())
        database.onboardings.find_one.return_value = {"status": "DRAFT"}
        request = SimpleNamespace(query_params={"customer_id": str(owner)})
        payload = ChatPayload(id=uuid4(), revision=0, sequence=0, content="Unsure")
        with (
            patch("app.main.get_database", return_value=database),
            patch("app.main.conversation_actor", new=AsyncMock(return_value=(owner, ObjectId()))),
            patch("app.main._owned_conversation", new=AsyncMock(return_value=conversation)),
            patch("app.main._read_answers", new=AsyncMock(return_value=[])) as read_answers,
            patch("app.main.run_in_threadpool", new=AsyncMock(side_effect=lambda fn, *args: fn(*args))),
            patch("app.main.interpret_answer", return_value=IntakeDecision(
                action="clarify", answer="", reply="What is the legal name?",
            )) as interpret,
        ):
            first = await send_chat_message(uuid4(), payload, request)
            self.assertEqual(first.revision, 1)
            self.assertEqual(len(first.turns), 1)
            database.onboardings.find_one.assert_awaited_once()
            read_answers.assert_awaited_once()
            database.conversations.find_one.assert_not_awaited()

            conversation.update(chat_revision=first.revision, chat_turns=[
                {"id": str(turn.id), "sequence": turn.sequence, "content": turn.content,
                 "clarification": turn.clarification} for turn in first.turns
            ])
            second = await send_chat_message(uuid4(), payload, request)
            self.assertEqual(first, second)
            interpret.assert_called_once()
            database.conversations.update_one.assert_awaited_once()
