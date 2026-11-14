# Customer 360 demo backend

From `backend/`:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

`POST /api/v1/login` returns the JSON boolean `true` without credentials.
This is a demo stub, not authentication. No database is required.
`FRONTEND_ORIGIN` defaults to `http://localhost:5173` for CORS.

Run the endpoint test from `backend/`:

```sh
.venv/bin/python -m unittest discover -s tests
```
