# Customer database

`collections.json` defines the starting MongoDB collections, validators and
indexes. `init_database.py` creates them in the database you specify.
All collections start empty. There are no seed documents or sample customer records.

From the repository root:

```bash
python -m venv database/.venv
database/.venv/bin/pip install -r database/requirements.txt
```

Create `database/.env` with `MONGODB_URI` and `MONGODB_DATABASE` if it does not
already exist. The file is ignored by Git. The initializer and backend load
these settings automatically; the initializer can also use variables already
set in the process environment.

Initialize from the repository root:

```powershell
database\.venv\Scripts\python.exe database\init_database.py
```

Use only your own trusted connection string. The database user needs collection
and index creation permissions.

| Core collection | Purpose |
| --- | --- |
| `users` | Admin/customer personas; optional `customer_id` links a person to a business |
| `customers` | Current business profile, contact, address and ownership details |
| `onboardings` | Application snapshot, products, status and requirements version |
| `conversations` | Chat sessions linked to an onboarding and customer |
| `messages` | Individual chat messages, ordered by timestamp and ID |
| `documents` | File metadata and optional GridFS `storage_id`, linked to an onboarding/conversation |
| `onboarding_requirements` | Versioned fields/documents required by product and jurisdiction |

Agent collections are empty placeholders with no custom validators or indexes:
`document_chunks`, `procedures`, `regulations`, `guardrails`, `audit_log`.
They can be revised or removed later. MongoDB still creates its default `_id` index.
No vector indexes, embeddings or agent rules are provisioned yet.

Core validators intentionally allow extra fields while checking the basic field
types. References use BSON ObjectIds and timestamps use BSON dates, not strings.
The backend must validate cross-collection references and customer ownership;
MongoDB validators do not provide foreign-key enforcement.

User emails are unique; normalize email casing in the application before writes.
Requirement keys are unique per version, with at most one active version per key.
Include product and jurisdiction in each key, such as `business_account_ca`.
Store the selected requirement ID/version on each onboarding and preserve the
submitted `application` snapshot when the customer's current profile changes.

The initializer is repeatable: it preserves documents and existing validators,
and creates the declared indexes. It does not drop collections or replace
conflicting indexes. Existing duplicates can cause unique-index creation to fail;
resolve those conflicts deliberately before retrying. A failed run may leave
some collections created, and rerunning safely continues setup.

The onboarding API uses Atlas for customer and user profiles, onboarding
snapshots, conversations, messages and document metadata. File binaries are
stored in the default GridFS bucket (`fs.files` and `fs.chunks`), created
automatically on first upload. The Atlas user must have read/write permissions
and permission to create GridFS collections and indexes.
