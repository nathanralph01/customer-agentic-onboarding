"""Voyage embeddings and Atlas Vector Search for onboarding references."""

import asyncio
import os
from copy import deepcopy
from time import monotonic
from typing import Literal

import httpx

MODEL = "voyage-4-lite"
DIMENSIONS = 256
INDEX = "c360_reference_vector_v1"
COLLECTIONS = ("regulations", "procedures")
SCOPE = {"dataset": "customer360-onboarding-reference", "jurisdiction": "CA", "version": 1}
REFERENCE_FIELDS = ("_id", "kind", "citation", "text", "version", "source_url")
FILTER = {**SCOPE, "embedding_model": MODEL}
CACHE_TTL_SECONDS = 120
CACHE_MAX_ENTRIES = 64
DEFINITION = {
    "type": "vectorSearch",
    "fields": [
        {"type": "vector", "path": "embedding", "numDimensions": DIMENSIONS, "similarity": "cosine"},
        *({"type": "filter", "path": field} for field in FILTER),
    ],
}


async def embed(texts: list[str], input_type: Literal["document", "query"]):
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise ValueError("Set VOYAGE_API_KEY in backend/.env.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": texts, "model": MODEL, "input_type": input_type, "output_dimension": DIMENSIONS},
        )
        response.raise_for_status()
    results = sorted(response.json()["data"], key=lambda row: row["index"])
    if [row["index"] for row in results] != list(range(len(texts))) or any(
        len(row["embedding"]) != DIMENSIONS for row in results
    ):
        raise ValueError("Voyage returned invalid reference embeddings.")
    return [row["embedding"] for row in results]


async def retrieve_references(database, query: str):
    # Scope results to this database session and limit how long any corpus change can be stale.
    cache = getattr(database, "_reference_search_cache", None)
    if cache is None:
        cache = database._reference_search_cache = {}
    cached = cache.get(query)
    if cached and cached[0] > monotonic():
        return deepcopy(cached[1])
    references = await _search_references(database, query)
    if len(cache) >= CACHE_MAX_ENTRIES:
        cache.pop(next(iter(cache)))
    cache[query] = (monotonic() + CACHE_TTL_SECONDS, deepcopy(references))
    return references


async def _search_references(database, query: str):
    vector, = await embed([query], "query")

    async def search(collection, limit):
        result = await database.call("aggregate", collection, pipeline=[
            {"$vectorSearch": {
                "index": INDEX, "path": "embedding", "queryVector": vector,
                "filter": FILTER, "numCandidates": 100, "limit": limit,
            }},
            {"$project": {**dict.fromkeys(REFERENCE_FIELDS, 1), "score": {"$meta": "vectorSearchScore"}}},
        ])
        return result["documents"]

    regulations, procedures = await asyncio.gather(search("regulations", 7), search("procedures", 4))
    if not regulations or not procedures:
        raise ValueError("Atlas Vector Search requires indexed regulations and procedures.")
    return [*regulations, *procedures]
