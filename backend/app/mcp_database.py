"""Application persistence through Atlas Managed MCP, including GridFS data.

PyMongo is installed only for its BSON codecs; no database driver is used here.
"""

import asyncio
import json
import math
from datetime import datetime, timezone
from types import SimpleNamespace

from bson import ObjectId, json_util
from bson.binary import Binary


class StorageError(RuntimeError):
    pass


class DuplicateKeyError(StorageError):
    pass


class NoFile(StorageError):
    pass


def encode(value):
    return json.loads(json_util.dumps(value))


def decode(value):
    return json_util.loads(json.dumps(value), json_options=json_util.JSONOptions(tz_aware=True))


async def tool(session, name, arguments):
    result = await session.call_tool(name, encode(arguments))
    if result.isError:
        # Inspect errors for classification, never return database details or credentials.
        message = " ".join(item.text for item in result.content if item.type == "text")
        if "E11000" in message or "duplicate key" in message.lower():
            raise DuplicateKeyError("A record with this key already exists.")
        raise StorageError(f"Atlas MCP operation {name} failed.")
    if not isinstance(result.structuredContent, dict):
        raise StorageError(f"Atlas MCP operation {name} returned no structured result.")
    return decode(result.structuredContent)


class MCPDatabase:
    def __init__(self, session, connection_id, name):
        self.session = session
        self.connection_id = connection_id
        self.name = name
        self.write_lock = asyncio.Lock()

    def __getitem__(self, collection):
        return MCPCollection(self, collection)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    async def call(self, name, collection, **arguments):
        try:
            return await tool(self.session, name, {
                "connectionId": self.connection_id, "database": self.name,
                "collection": collection, **arguments,
            })
        except StorageError:
            raise
        except Exception:
            raise StorageError("Atlas MCP is unavailable. Retry the request.") from None


class MCPCollection:
    def __init__(self, database, name):
        self.database = database
        self.name = name

    async def find(self, query, sort=None, projection=None):
        # Keyset pagination avoids MCP's default ten-record limit and byte cap.
        documents = []
        last_id = None
        while True:
            page_query = query if last_id is None else {"$and": [query, {"_id": {"$gt": last_id}}]}
            kwargs = {"filter": page_query, "sort": {"_id": 1}, "limit": 50, "responseBytesLimit": 1048576}
            if projection:
                kwargs["projection"] = projection
            result = await self.database.call("find", self.name, **kwargs)
            page = result.get("documents")
            if not isinstance(page, list):
                raise StorageError("Atlas MCP returned invalid query results.")
            if not page:
                if result.get("queryResultsCount", 0):
                    raise StorageError("A database record exceeded the MCP response size limit.")
                break
            next_id = page[-1].get("_id")
            if next_id is None or next_id == last_id:
                raise StorageError("Atlas MCP query pagination did not advance.")
            documents.extend(page)
            last_id = next_id
        if sort:
            key, direction = sort
            documents.sort(key=lambda document: (document.get(key) is not None, document.get(key)),
                           reverse=direction < 0)
        return documents

    async def find_one(self, query):
        result = await self.database.call("find", self.name, filter=query, limit=1, responseBytesLimit=1048576)
        documents = result.get("documents")
        if not isinstance(documents, list):
            raise StorageError("Atlas MCP returned invalid query results.")
        if not documents and result.get("queryResultsCount", 0):
            raise StorageError("A database record exceeded the MCP response size limit.")
        return documents[0] if documents else None

    async def count_documents(self, query):
        return len(await self.find(query, projection={"_id": 1}))

    async def upsert(self, query, insert_fields):
        try:
            await self.database.call("update-many", self.name, filter=query,
                                     update={"$setOnInsert": insert_fields}, upsert=True)
        except DuplicateKeyError:
            existing = await self.find_one(query)
            if existing is None:
                raise
            return existing
        result = await self.find_one(query)
        if result is None:
            raise StorageError("Atlas MCP upsert could not be verified.")
        return result

    async def insert_one(self, document):
        document.setdefault("_id", ObjectId())
        await self.database.call("insert-many", self.name, documents=[document])
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query, update):
        # An exact ID guarantees at most one match, including with extra predicates.
        if isinstance(query.get("_id"), (ObjectId, str)):
            return await self.database.call("update-many", self.name, filter=query, update=update)
        # Resolve exactly one _id because MCP exposes update-many, not update-one.
        existing = await self.find_one(query)
        if existing is not None:
            return await self.database.call("update-many", self.name,
                                            filter={**query, "_id": existing["_id"]}, update=update)

    async def delete_one(self, query):
        existing = await self.find_one(query)
        if existing is not None:
            return await self.database.call("delete-many", self.name, filter={"_id": existing["_id"]})


class MCPBucket:
    """GridFS-compatible file storage over MCP's BSON-aware CRUD tools."""

    # Base64 expands binary by 4/3; the hosted service limits whole HTTP requests.
    CHUNK_SIZE = 16 * 1024

    def __init__(self, database):
        self.database = database

    async def upload_from_stream(self, filename, content, metadata):
        storage_id = ObjectId()
        try:
            for n, offset in enumerate(range(0, len(content), self.CHUNK_SIZE)):
                await self.database["fs.chunks"].insert_one({
                    "files_id": storage_id, "n": n,
                    "data": Binary(content[offset:offset + self.CHUNK_SIZE]),
                })
            await self.database["fs.files"].insert_one({
                "_id": storage_id, "length": len(content), "chunkSize": self.CHUNK_SIZE,
                "uploadDate": datetime.now(timezone.utc), "filename": filename, "metadata": metadata,
            })
        except Exception:
            await self.delete(storage_id, missing_ok=True)
            raise
        return storage_id

    async def read(self, storage_id):
        file = await self.database["fs.files"].find_one({"_id": storage_id})
        if file is None:
            raise NoFile("Document content not found.")
        if not 0 <= file["length"] <= 10 * 1024 * 1024 or file["chunkSize"] <= 0:
            raise StorageError("Invalid document storage metadata.")
        parts = []
        for n in range(math.ceil(file["length"] / file["chunkSize"])):
            chunk = await self.database["fs.chunks"].find_one({"files_id": storage_id, "n": n})
            if chunk is None or not isinstance(chunk.get("data"), bytes):
                raise NoFile("Document content is incomplete.")
            expected = min(file["chunkSize"], file["length"] - n * file["chunkSize"])
            if len(chunk["data"]) != expected:
                raise NoFile("Document content is incomplete.")
            parts.append(bytes(chunk["data"]))
        return b"".join(parts)

    async def delete(self, storage_id, missing_ok=False):
        if not missing_ok and await self.database["fs.files"].find_one({"_id": storage_id}) is None:
            raise NoFile("Document content not found.")
        await self.database.call("delete-many", "fs.chunks", filter={"files_id": storage_id})
        await self.database["fs.files"].delete_one({"_id": storage_id})
