"""Create Customer collections without inserting data or changing existing validators."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import CollectionInvalid, PyMongoError


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    uri = os.environ.get("MONGODB_URI")
    name = os.environ.get("MONGODB_DATABASE")
    if not uri or not name:
        raise SystemExit("Set MONGODB_URI and MONGODB_DATABASE before running this script.")

    definitions = json.loads(Path(__file__).with_name("collections.json").read_text())
    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        client.admin.command("ping")
        database = client[name]
        existing = set(database.list_collection_names())
        for definition in definitions:
            collection_name = definition["name"]
            if collection_name not in existing:
                options = {}
                if "validator" in definition:
                    options = {
                        "validator": definition["validator"],
                        "validationLevel": "strict",
                        "validationAction": "error",
                    }
                try:
                    database.create_collection(collection_name, **options)
                    print(f"Created {collection_name}")
                except CollectionInvalid:
                    print(f"Already exists: {collection_name}; leaving validator unchanged")
            else:
                print(f"Already exists: {collection_name}; leaving validator unchanged")
            for index in definition.get("indexes", []):
                options = {key: value for key, value in index.items() if key != "keys"}
                database[collection_name].create_index(list(index["keys"].items()), **options)
    print("Setup complete. No documents were inserted or removed.")


if __name__ == "__main__":
    try:
        main()
    except PyMongoError:
        # Driver errors can include connection details. Keep credentials out of output.
        raise SystemExit(
            "Database setup failed. Check connectivity, database permissions and existing "
            "index definitions. Resolve any conflicts before rerunning; setup may be partial."
        ) from None
