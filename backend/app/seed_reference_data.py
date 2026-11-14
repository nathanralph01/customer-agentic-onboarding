"""Validate and optionally load the versioned onboarding reference corpus."""

import argparse
import asyncio
import json
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "database" / "reference_data"
COLLECTIONS = ("regulations", "procedures")
PUBLIC_KINDS = {"statute", "regulation", "regulatory_guidance", "supervisory_guideline"}
DATASET = "customer360-onboarding-reference"


def load_reference_data():
    corpus = {
        collection: json.loads((REFERENCE_DIR / f"{collection}.json").read_text(encoding="utf-8"))
        for collection in COLLECTIONS
    }
    ids = set()
    for collection, documents in corpus.items():
        for document in documents:
            identifier = document["_id"]
            if identifier in ids or document["dataset"] != DATASET or not identifier.startswith("c360:"):
                raise ValueError(f"Invalid or duplicate reference ID: {identifier}")
            if not all(document[key] for key in ("text", "title", "citation", "jurisdiction", "version", "topic")):
                raise ValueError(f"Incomplete reference: {identifier}")
            if collection == "regulations":
                if document["kind"] not in PUBLIC_KINDS or not document["source_url"].startswith("https://"):
                    raise ValueError(f"Invalid public source: {identifier}")
            elif document["kind"] != "demo_bank_policy":
                raise ValueError(f"Invalid demo policy: {identifier}")
            ids.add(identifier)

    cases = json.loads((REFERENCE_DIR / "retrieval_cases.json").read_text(encoding="utf-8"))
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate retrieval case ID.")
    for case in cases:
        if not case["query"] or not case["expected_answer"] or not set(case["expected_source_ids"]) <= ids:
            raise ValueError(f"Invalid retrieval case: {case['id']}")
    return corpus, cases


async def seed(corpus):
    from .main import app, lifespan

    async with lifespan(app):
        database = app.state.database
        for collection, documents in corpus.items():
            for document in documents:
                key = {"_id": document["_id"], "dataset": DATASET}
                saved = await database[collection].upsert(key, document)
                if any(saved.get(field) != value for field, value in document.items()):
                    raise ValueError(f"Reference {document['_id']} already has different content. Use a new version.")
            print(f"{collection}: verified {len(documents)} documents in Atlas")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the reference documents to the configured Atlas database.")
    args = parser.parse_args()
    corpus, cases = load_reference_data()
    for collection, documents in corpus.items():
        print(f"{collection}: {len(documents)} validated documents")
    print(f"{len(cases)} retrieval evaluation cases")
    if args.apply:
        try:
            asyncio.run(seed(corpus))
        except ModuleNotFoundError as error:
            raise SystemExit(
                f"Missing backend dependency: {error.name}. "
                "Run .venv/bin/python -m pip install -r requirements.txt from backend/."
            ) from None
        except (RuntimeError, ValueError) as error:
            # Storage errors are sanitized in the MCP adapter.
            message = str(error) if isinstance(error, ValueError) else "Check Atlas Managed MCP configuration and write permissions."
            raise SystemExit(f"Reference import stopped. {message}") from None


if __name__ == "__main__":
    main()
