import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import ObjectId
from bson.binary import Binary

from app.mcp_database import MCPDatabase, MCPBucket, StorageError, DuplicateKeyError, decode, encode, tool


def result(data):
    return SimpleNamespace(isError=False, structuredContent=encode(data))


class MCPDatabaseTests(unittest.IsolatedAsyncioTestCase):
    def test_bson_roundtrip_preserves_existing_schema_types(self):
        document = {"_id": ObjectId(), "created_at": datetime.now(timezone.utc), "data": Binary(b"\x00\xff")}
        decoded = decode(encode(document))
        self.assertEqual(decoded["_id"], document["_id"])
        self.assertEqual(decoded["data"], b"\x00\xff")
        self.assertLess(abs((decoded["created_at"] - document["created_at"]).total_seconds()), .001)

    async def test_find_paginates_even_when_byte_cap_returns_a_short_page(self):
        ids = sorted([ObjectId(), ObjectId()])
        session = AsyncMock()
        session.call_tool.side_effect = [
            result({"documents": [{"_id": ids[0], "sequence": 2}], "appliedLimits": ["responseBytesLimit"]}),
            result({"documents": [{"_id": ids[1], "sequence": 1}]}),
            result({"documents": []}),
        ]
        db = MCPDatabase(session, "connection", "test")
        documents = await db["messages"].find({"role": "user"}, sort=("sequence", 1))
        self.assertEqual([d["sequence"] for d in documents], [1, 2])
        second = session.call_tool.call_args_list[1].args[1]
        self.assertEqual(decode(second["filter"]), {"$and": [{"role": "user"}, {"_id": {"$gt": ids[0]}}]})

    async def test_oversized_result_fails_instead_of_silently_losing_records(self):
        session = AsyncMock()
        session.call_tool.return_value = result({"documents": [], "queryResultsCount": 1})
        with self.assertRaises(StorageError):
            await MCPDatabase(session, "connection", "test")["files"].find({})

    async def test_duplicate_errors_are_classified_without_exposing_data(self):
        session = AsyncMock()
        session.call_tool.return_value = SimpleNamespace(isError=True, content=[SimpleNamespace(type="text", text="E11000 duplicate key sensitive data")])
        with self.assertRaises(DuplicateKeyError) as caught:
            await tool(session, "insert-many", {})
        self.assertNotIn("sensitive", str(caught.exception))

    async def test_partial_upload_cleans_up_its_own_gridfs_data(self):
        session = AsyncMock()
        session.call_tool.side_effect = [result({"insertedCount": 1}), RuntimeError("network failure"), result({"deletedCount": 1}), result({"documents": []})]
        bucket = MCPBucket(MCPDatabase(session, "connection", "test"))
        with self.assertRaises(StorageError):
            await bucket.upload_from_stream("test.txt", b"x" * (bucket.CHUNK_SIZE + 1), {})
        calls = session.call_tool.call_args_list
        storage_id = decode(calls[0].args[1])["documents"][0]["files_id"]
        self.assertEqual(calls[2].args[0], "delete-many")
        self.assertEqual(decode(calls[2].args[1])["filter"], {"files_id": storage_id})
