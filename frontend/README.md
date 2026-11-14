# Customer 360 frontend

Marketing landing page and customer workspace built with React, TypeScript, Vite, Tailwind CSS v4 and shadcn-style components. The demo login connects to a FastAPI backend.

## Development

```sh
npm install
npm start
```

Vite serves the page at http://localhost:5173.

```sh
npm run lint
npm run build
npm run preview
```

The globe pauses off screen, in background tabs, and when reduced motion is requested. Statistics and testimonials are illustrative demo content.

## Customer workspace demo

Start the backend using the instructions in `../backend/README.md`, then run
`npm install` and `npm start` from this directory. Open the landing page and
choose **Log in**, then **Log in as customer**. A successful response from
`POST /api/v1/login` opens `/customer`.

The demo session lasts for the browser tab and can be ended with **Log out**.
This is a UI demo, not real authentication. **Start onboarding** opens
`/customer/onboarding`, a scripted chatbot that gathers business details, owners
and banking needs. Customer profiles, onboarding drafts, conversations and
answers are saved in the configured Atlas database. Existing browser-session
conversations are migrated on first load. Company documents are uploaded to
Atlas GridFS, with metadata in the `documents` collection; they can be listed,
downloaded and removed from the workspace. Files are not read or processed by
an agent. Uploads accept PDF, DOCX, TXT, CSV, PNG or JPG files up to 10 MB,
with up to 10 files per conversation. No application is submitted for
verification. Other workspace options remain disabled placeholders.

In development, Vite proxies `/api` to `http://127.0.0.1:8000`. For a separately
hosted API, set `VITE_API_URL` to the full base URL (including `/api/v1`) before
building, and set the backend's `FRONTEND_ORIGIN` to the frontend origin.
