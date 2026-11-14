# Customer 360 backend

The backend reads `MONGODB_URI` and `MONGODB_DATABASE` from the process
environment or `database/.env`. Initialize the Atlas schema from the repository
root before starting the API:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe database\init_database.py
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

The demo onboarding flow stores a synthetic customer and user profile,
onboardings, conversations, messages, document metadata and document content in
Atlas. File content uses GridFS; the `fs.files` and `fs.chunks` collections are
created automatically on the first upload. The Atlas user needs permission to
read/write the database and create these GridFS collections and indexes.
Existing local browser conversations are migrated on first load. The login
endpoint still returns `true` without credentials and is not authentication.
Uploads accept PDF, DOCX, TXT, CSV, PNG or JPG files up to 10 MB, with up to 10
files per conversation. Documents can be downloaded or deleted; they are not
scanned or processed by an agent.

`FRONTEND_ORIGIN` defaults to `http://localhost:5173` for CORS. Run the endpoint
tests from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Onboarding chatbot MVP

Open the customer demo and select business onboarding. FastAPI supplies the
questions, tracks progress, and saves chat turns and accepted answers in Atlas.
The existing conversation history can resume previously saved drafts.

The chatbot starts in guided mode with MongoDB alone. To enable model-assisted
follow-ups, install the updated backend requirements and the LangChain
integration package for your chosen provider. Set `ONBOARDING_CHAT_MODEL` to
`provider:model` and configure that provider's credentials before starting
Uvicorn. Choose a chat model that supports LangChain structured output.

The backend sends synthetic chat messages and recent clarifications to the
configured provider through LangChain. The intake instructions live in
`app/skills/onboarding-intake/SKILL.md`. A provider error keeps the current
question open so the message can be retried.

The frontend calls `POST /api/v1/conversations/{conversation_id}/chat` with a
message UUID, the observed conversation revision, the question sequence, and
message content. Resending a recent message with the same UUID is safe.
The chat endpoint uses MongoDB transactions to save an accepted answer and the
associated chat turn together. Use Atlas or a MongoDB replica set.
