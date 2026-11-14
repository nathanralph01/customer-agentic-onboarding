## Backend Implementation

Python FastAPI service (single deployable) that hosts the REST API and the LangGraph agent workflow in the same process. MongoDB Atlas is the only datastore. All endpoints are prefixed `/api/v1`.

### Project layout
- `app/main.py` - FastAPI app, CORS, router registration
- `app/demo/` - seeded persona endpoint and the `get_actor` dependency
- `app/routers/` - `customer`, `admin`
- `app/services/` - onboarding state machine, action reconciliation, risk routing, audit
- `app/agents/` - LangGraph workflow, Risk / Compliance / Document agents, tools, prompts, guardrail middleware
- `app/db/` - Mongo client, collection accessors, index setup
- `app/schemas/` - Pydantic models for requests, responses and agent structured outputs
- `scripts/` - seed data, regulation/procedure ingestion, vector index creation
- `tests/`

### Users and access (demo)
- No endpoint authentication, tokens or passwords. The API is for demo use only and must not be deployed with real data.
- `GET /demo/users` returns the seeded personas (customers and admins). The login portal lets the user pick one and the frontend redirects to the customer or admin site by the persona's role.
- Customer endpoints take the acting customer as a `customer_id` query parameter, and admin endpoints take an optional `admin_id` for audit entries. Both are trusted as given.
- Routes stay split under `/customer` and `/admin` so the structure matches what real role-based auth would protect later. A single FastAPI dependency (`get_actor`) reads these ids, so auth can be added in one place.
- Audit entries still record the actor id and role.

### Onboarding state machine
States: `APPLIED`, `VERIFYING`, `NEEDS_INFO`, `RISK_ASSESSMENT`, `COMPLIANCE_CHECK`, `DOCUMENT_GENERATION`, `ADMIN_REVIEW`, `AWAITING_SIGNATURE`, `PROVISIONING`, `ONBOARDED`, `PAUSED`, `CANCELLED`.

- Flow: `APPLIED` -> `VERIFYING` -> `RISK_ASSESSMENT` -> `COMPLIANCE_CHECK` -> `ADMIN_REVIEW` (risk gate) -> `DOCUMENT_GENERATION` -> `ADMIN_REVIEW` (document gate) -> `AWAITING_SIGNATURE` -> `PROVISIONING` -> `ONBOARDED`.
- Human review gates (workflow pauses via LangGraph `interrupt`) after Risk + Compliance and after Document generation, before generated documents are released to the customer. Admin decisions: `continue`, `pause`, `cancel`, or `request_info` (moves to `NEEDS_INFO`).
- `PAUSED` and `NEEDS_INFO` store the previous state and gate identifier so the run resumes where it stopped.
- Cancel is allowed from any non-terminal state, by an admin, with customer cancellation as stretch.
- Every transition writes an `audit_log` entry (actor, from, to, reason, timestamp).
- Use sandbox adapters with independently persisted state for business verification, signing, and provisioning. Signing resumes the agent run, which provisions the account and advances to `ONBOARDED` after verifying the record.

### Customer endpoints
All customer endpoints take `customer_id` as a query parameter.

| Method | Path | Purpose |
|---|---|---|
| POST | `/customer/onboardings` | Start onboarding with the application data (business details, owners, products requested). Starts the workflow and returns the onboarding id and required documents |
| GET | `/customer/onboardings` | List the customer's onboardings |
| GET | `/customer/onboardings/{id}` | Progress: current step, steps completed / remaining, estimated completion, contact details for the team on the current step |
| POST | `/customer/onboardings/{id}/documents` | Upload a requested document or supply missing information (resumes from `NEEDS_INFO`) |
| GET | `/customer/onboardings/{id}/documents` | List generated and uploaded documents, with download |
| POST | `/customer/onboardings/{id}/sign` | Mocked e-sign: records signer and timestamp in the sandbox signing system and resumes the agent run |
| POST | `/customer/onboardings/{id}/cancel` | (Stretch) Cancel the onboarding |
| GET | `/customer/onboardings/{id}/summary` | Completed onboarding details: account status, benefits, access |
| GET | `/customer/onboardings/{id}/events` | (Stretch) Server-sent events for live status |

### Admin endpoints
Admin endpoints take an optional `admin_id` query parameter for audit entries.

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/onboardings` | List and filter by status, risk level, date, sector |
| GET | `/admin/onboardings/{id}` | Full detail: application, state history, agent outputs, documents, audit trail |
| GET | `/admin/reviews` | Queue of onboardings waiting at a review gate |
| POST | `/admin/onboardings/{id}/review` | Submit decision: `continue`, `pause`, `cancel`, or `request_info`, with comments and optional edits. Resumes the paused workflow |
| GET | `/admin/onboardings/{id}/risk` | Risk assessment: overall score, per-category scores for the risk map, agent explanations with citations |
| GET | `/admin/onboardings/{id}/risk/prediction` | (Stretch) Predicted risk trend (up / down / stable) with rationale |
| GET | `/admin/risk-appetite` | Bank's risk appetite for a sector and customer type (query params) |
| GET | `/admin/onboardings/{id}/pricing` | (Stretch) Agent-recommended pricing, within the risk appetite |
| PUT | `/admin/onboardings/{id}/pricing` | (Stretch) Adjust pricing. Records original vs adjusted and the reason |
| POST | `/admin/onboardings/{id}/sign` | (Stretch) Mocked e-sign for the bank side, if needed |
| GET | `/admin/guardrails` | Active guardrails and version history |
| GET | `/admin/guardrail-proposals` | Proposed guardrail changes generated from admin overrides |
| POST | `/admin/guardrail-proposals/{id}/decision` | Approve or reject. Approval creates a new guardrail version |
| GET | `/admin/metrics` | (Stretch) Average time to onboard, count by state, agent override rate |

### Agentic orchestration
The agents run in-process. They are invoked by the services above, not exposed as free-form chat endpoints.

- **Graph:** one LangGraph workflow per onboarding, `thread_id = onboarding_id`. State and checkpoints are persisted in MongoDB, so a run can resume after a pause, a review wait, a restart, or days later.
- **Nodes:** Verify, Risk assessment, Compliance, review gates (`interrupt`), Document preparation, signature verification, Provision, and Guardrail learning.
- **Routing:** deterministic edges for the fixed flow, with agent-decided branching only where needed (for example, Compliance finds missing information and routes to `NEEDS_INFO`).
- **Agents:** created with LangChain `create_agent`, with tools and a system prompt each:
  - Risk (MVP priority): retrieves procedures and verified precedents, reads the applicable risk policy, and persists a validated assessment with overall tier, per-category scores, evidence citations, rationale, missing inputs, and policy version. Deterministic rules based on that policy route material gaps to `NEEDS_INFO` and flag high-risk cases for explicit admin disposition. Reassess when relevant inputs change.
  - Compliance: retrieves regulations (FINTRAC, PCMLTFA, PIPEDA, OSFI) with hybrid search, returns pass / fail / needs-info per requirement with cited sources.
  - Document: generates the onboarding documents (PDF or markdown) from the profile, reviewed risk result and templates.
  - Future risk prediction (stretch): trend estimate from the profile and similar past onboardings.
- **Outputs:** every agent returns a Pydantic-validated structured result with `confidence` and `sources`. Invalid output triggers a retry, then escalates to an admin.
- **Authority:** agents execute allowed tools under the applicable policy. Check the relevant tool policy and review prerequisites before each write. Capture the acting agent, triggering request or approval, and policy version. Risk and document release follow their respective review gates.
- **Endpoints for the workflow:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/agents/runs/{onboarding_id}` | Run status, current node, last checkpoint |
| POST | `/admin/agents/runs/{onboarding_id}/retry` | Retry a failed node |
| GET | `/admin/agents/runs/{onboarding_id}/trace` | Agent steps, tool calls and outputs for the admin detail view |

### Verified execution and recovery

- Use an Atlas action ledger keyed by a unique operation ID derived from the onboarding, step, and intended action revision. Record the intent and target before dispatch, then store the external reference and verification evidence. Pass the operation ID as the idempotency key and make it queryable in the sandbox system.
- A tool response records dispatch or acceptance. Mark an action verified only after reading the target record and checking it against the intended effect. If the result is uncertain, reconcile by operation ID first. Retry with the same key when the adapter supports safe retries. Pause unresolved or conflicting writes for admin review.
- Persist the ledger independently of the graph checkpoint. On startup or admin retry, claim the run with a conditional Atlas lease, load its checkpoint, and reconcile any incomplete actions before resuming. Reuse verified results when re-entering a node. Apply the same idempotency rule to local document generation.
- On a contract mismatch, inspect the sandbox system's current schema or capabilities. Retrieve verified recovery examples from Atlas Vector Search by integration and contract metadata. Validate a supported mapping against the current contract and verify the resulting effect. Pause for operator input if a mapping cannot be confirmed.
- Treat pause and cancel as dispatch boundaries checked before the next tool write. Reconcile any action already in flight and expose its result to the reviewer.

### Memory and adaptive guardrails
- **Short-term memory:** MongoDB-backed LangGraph checkpointer, keyed by onboarding.
- **Long-term memory:** store customer facts and admin overrides. Index verified prior risk outcomes and successful integration recoveries for retrieval. Use the run ledger and target records as the source of truth for the current case.
- **Guardrails:** stored as versioned documents (risk thresholds, required documents per product and sector, escalation rules). Agents load the active version at the start of each run through middleware.
- **Learning loop:** when an admin changes an agent recommendation (risk level, pricing, compliance result), the override is stored with its reason. The Guardrail-learning step analyses recent overrides and creates a `guardrail_proposal`. An admin must approve it before it becomes the new active version. All versions are kept.

### Data model (MongoDB collections)
| Collection | Contents |
|---|---|
| `users` | id, name, role, customer_id (seeded personas, no credentials) |
| `customers` | business profile, owners, sector, nested application data |
| `onboardings` | customer_id, state, state history, current step, ETA, pricing (recommended, adjusted), risk summary |
| `agent_checkpoints` / `agent_memory` | LangGraph checkpoints, long-term memory and verified retrieval examples |
| `agent_actions` | operation ID, onboarding ID, step, target, intent, state, external reference, verification evidence, and authority |
| `risk_assessments` | input revision, overall tier, category scores, citations, missing inputs, routing, policy version |
| `documents` | metadata, type, status, storage location or content |
| `document_chunks` | chunked uploaded document text with embeddings (vector) |
| `regulations` | regulation text chunks, jurisdiction, source (vector) |
| `procedures` | bank risk and onboarding procedures, risk appetite by sector (vector) |
| `guardrails` | key, version, rule, status, created_by |
| `guardrail_proposals` | proposed change, supporting overrides, status |
| `overrides` | admin changes to agent outputs, with reasons |
| `audit_log` | append-only record of actions by users and agents |

**Indexes.** Prioritize Vector Search on `agent_memory` with metadata filters for integration, contract version, product and sector. Use reference-data indexes on `regulations`, `procedures`, and `document_chunks` as needed. Add a unique index on action operation ID, an index on actions by onboarding and state for reconciliation, and indexes on onboarding customer and state for lookups.

### Estimated completion and contacts
- ETA = sum of remaining steps' average durations (configured per step, updated from completed onboardings) plus any time spent waiting at review gates.
- Contacts per step come from a static configuration (team name, email, phone) returned with the progress endpoint.

### Errors and reliability
- Consistent error response format, with a request id.
- LLM calls have a timeout and a limited number of retries. A failed node leaves the run in a recoverable failed state visible in the admin run view.
- Uploaded document text is treated as untrusted data: it is delimited in prompts and never allowed to change instructions or tool calls.

### Configuration
Environment variables: Mongo connection string, Google Cloud project and credentials, Gemini model names, LangSmith keys, feature flags for stretch features. CORS allows the frontend origin only. No secrets in the repository.

### Testing
- Unit tests for the state machine.
- Integration tests for each endpoint using seeded data.
- Agent evaluation cases for the seeded demo scenarios, asserting expected risk level and compliance outcome.
- End-to-end checks for the full journey, high-risk and missing-evidence routing, crash after external commit with one resulting account, and contract drift with validated recovery or operator escalation.
