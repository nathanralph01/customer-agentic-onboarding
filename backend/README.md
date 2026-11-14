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
