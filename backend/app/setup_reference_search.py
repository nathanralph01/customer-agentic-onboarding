"""Embed the seeded corpus, create its vector indexes, or probe retrieval."""

import argparse
import asyncio

from .main import app, lifespan
from .reference_search import COLLECTIONS, DEFINITION, DIMENSIONS, INDEX, MODEL, SCOPE, embed, retrieve_references


async def setup(query: str | None):
    async with lifespan(app):
        database = app.state.database
        if query is not None:
            for row in await retrieve_references(database, query):
                print(f"{row['score']:.3f}  {row['citation']}  ({row['_id']})")
            return

        for name in COLLECTIONS:
            collection = database[name]
            records = await collection.find(SCOPE)
            if not records:
                raise ValueError(f"Seed {name} before building the search index.")
            pending = [
                row for row in records if row.get("embedding_model") != MODEL
                or len(row.get("embedding", [])) != DIMENSIONS
            ]
            if pending:
                vectors = await embed([f"{row['title']}\n{row['text']}" for row in pending], "document")
                for row, vector in zip(pending, vectors, strict=True):
                    await collection.update_one({"_id": row["_id"], **SCOPE}, {"$set": {
                        "embedding": vector, "embedding_model": MODEL,
                    }})
            await database.call("create-index", name, name=INDEX, definition=DEFINITION)
            print(f"{name}: {len(pending)} embeddings written; vector index {INDEX} requested.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="Check retrieval and print the ranked citations.")
    try:
        asyncio.run(setup(parser.parse_args().query))
    except Exception as error:
        raise SystemExit(f"Reference search setup failed ({type(error).__name__}). Check Voyage credentials, Atlas index permissions, and index readiness.") from None
