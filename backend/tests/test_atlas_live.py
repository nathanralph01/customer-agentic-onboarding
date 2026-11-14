"""Opt-in end-to-end tests against the configured hackathon sandbox."""

import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


@unittest.skipUnless(os.getenv("RUN_ATLAS_INTEGRATION") == "1", "Set RUN_ATLAS_INTEGRATION=1 to exercise the Atlas sandbox")
class AtlasLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_answers_and_binary_document_roundtrip(self):
        conversation_id = str(uuid4())
        print(f"Live test client ID: {conversation_id}", flush=True)
        async with lifespan(app):
            db = app.state.database
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=300) as client:
                    payload = {"id": conversation_id, "startedAt": datetime.now(timezone.utc).isoformat(), "answers": ["MCP integration test"]}
                    response = await client.post("/api/v1/conversations", json=payload)
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(response.json()["answers"], payload["answers"])
                    # Replay must not duplicate the conversation or its answers.
                    replay = await client.post("/api/v1/conversations", json=payload)
                    self.assertEqual(replay.status_code, 201, replay.text)
                    self.assertEqual(replay.json(), response.json())
                    conflict = await client.post(f"/api/v1/conversations/{conversation_id}/answers", json={"sequence": 0, "content": "different"})
                    self.assertEqual(conflict.status_code, 409)
                    out_of_order = await client.post(f"/api/v1/conversations/{conversation_id}/answers", json={"sequence": 3, "content": "too early"})
                    self.assertEqual(out_of_order.status_code, 409)
                    saved = await client.post(f"/api/v1/conversations/{conversation_id}/answers", json={"sequence": 1, "content": "second answer"})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual(len(saved.json()["answers"]), 2)
                    # Cross the chunk boundary and exercise BSON binary encoding.
                    content = bytes(range(256)) * 1100
                    uploaded = await client.post(f"/api/v1/conversations/{conversation_id}/documents", files={"file": ("../roundtrip.txt", content, "text/plain")})
                    self.assertEqual(uploaded.status_code, 201, uploaded.text)
                    document = uploaded.json()
                    self.assertEqual(document["filename"], "roundtrip.txt")
                    self.assertEqual(document["sizeBytes"], len(content))
                    downloaded = await client.get(f"/api/v1/documents/{document['id']}/download")
                    self.assertEqual(downloaded.status_code, 200, downloaded.text[:200])
                    self.assertEqual(downloaded.content, content)
                    listed = await client.get(f"/api/v1/conversations/{conversation_id}/documents")
                    self.assertEqual([d["id"] for d in listed.json()], [document["id"]])
                    deleted = await client.delete(f"/api/v1/conversations/{conversation_id}/documents/{document['id']}")
                    self.assertEqual(deleted.status_code, 200, deleted.text)
                    missing = await client.get(f"/api/v1/documents/{document['id']}/download")
                    self.assertEqual(missing.status_code, 404)
                    conversations = await client.get("/api/v1/conversations")
                    self.assertEqual(conversations.status_code, 200, conversations.text)
                    self.assertEqual(sum(c["id"] == conversation_id for c in conversations.json()), 1)
            finally:
                # Remove only records belonging to this test's random client UUID.
                conversation = await db["conversations"].find_one({"client_id": conversation_id})
                if conversation:
                    from app.mcp_database import MCPBucket
                    for document in await db["documents"].find({"conversation_id": conversation["_id"]}):
                        await MCPBucket(db).delete(document["storage_id"], missing_ok=True)
                        await db["documents"].delete_one({"_id": document["_id"]})
                    await db.call("delete-many", "messages", filter={"conversation_id": conversation["_id"]})
                    await db["conversations"].delete_one({"_id": conversation["_id"]})
                await db.call("delete-many", "onboardings", filter={"client_id": conversation_id})
