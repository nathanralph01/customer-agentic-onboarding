# Customer 360

Detailed plans: [FRONTEND-PLAN.md](FRONTEND-PLAN.md) and [BACKEND-PLAN.md](BACKEND-PLAN.md).

## Hackathon Requirements

**Event:** MongoDB x LangChain x Google Cloud Hackathon, Toronto, Saturday November 14 (single day). Teams of up to 4.

**Goal:** Build an agentic system that holds context across sessions, adapts its guardrails, and reliably turns information into action. It should be durable infrastructure, not a disconnected demo.

### Mandatory technology
| # | Requirement | How Customer 360 meets it |
|---|-------------|---------------------------|
| 1 | MongoDB Atlas as the data and context layer | Customer profiles, onboardings, documents, regulations, procedures, guardrails, and audit log are stored in Atlas |
| 2 | Atlas Vector Search | Retrieval of verified risk precedents, integration recovery examples, and reference material |
| 3 | Agentic Memory | Short-term run state (checkpointer) and long-term memory (store) for customer facts, past decisions, and admin overrides |
| 4 | LangChain for agent experiences and workflows | LangChain and LangGraph for the onboarding workflow and specialist agents |
| 5 | Google Cloud as the cloud foundation | Gemini on Vertex AI, hosting on Cloud Run |

### Mandatory system behaviours
| # | Requirement | How Customer 360 meets it |
|---|-------------|---------------------------|
| 6 | Must be an agentic workflow, not just AI-assisted | A LangGraph workflow coordinates agents (Risk, Compliance, Document), which call tools and take actions |
| 7 | Holds context across sessions | A customer or admin can leave and return days later, and the workflow resumes from persisted state and memory |
| 8 | Adapts its guardrails | Guardrails (risk thresholds, required documents, escalation rules) are stored in MongoDB and updated, with human approval, from admin overrides. Changes are versioned and audited |
| 9 | Reliably turns information into action | Agents use structured outputs and tools to verify business records, generate documents, and provision sandbox accounts, with verified effects, recovery, and human review gates |

### Judging considerations
- Durable and impactful: real persistence, audit trail, and a path beyond the demo.
- Solves a real problem: customer onboarding is slow, and the demo measures days versus minutes.
- Working demo within the single day, with clear scope and a defined MVP.

## Selected track: Durable cross-system execution

Customer 360 agents carry a banking application through verification, risk assessment, compliance, document preparation, and final provisioning. The demo uses independently stateful sandbox systems for business verification, signing, and downstream account provisioning. Customer submission and signature, along with bank review decisions, are explicit handoffs. Agents resume and perform the remaining work.

- **Verify effects.** Record each intended write before dispatch. Read back the target record or receipt to confirm the effect, and leave ambiguous outcomes pending reconciliation.
- **Resume from verified state.** Persist LangGraph checkpoints and the action ledger in Atlas. Reconcile unfinished actions before retrying so a crash after an external write creates no duplicate records.
- **Adapt to system changes.** Detect a changed tool contract, retrieve verified recovery examples through Atlas Vector Search, and validate the revised mapping before resuming. Route uncertain or unsupported changes to an operator.

## Project Idea
Customer 360 is an agentic web application that carries out customer onboarding tasks. This can be applied to any business, but this demo is focused on banking. It is a single workflow that takes a business through the application process, risk and compliance review, document execution, and final onboarding. The name of the application is Customer 360.

The project is built with MongoDB Atlas, LangChain and Google Cloud.

The application contains several AI agents, each with a specific task:
- Risk assessment
- Document generation
- Legal and local legislative compliance
- Future risk prediction (stretch)

Agentic context is stored in MongoDB Atlas and accessed through vector search. Relevant context: customer profiles, local and federal rules and laws, company risk and onboarding procedures, and documents and metadata.

The customer journey:
Apply -> Verify -> Assess Risk -> Check Compliance -> Risk Review -> Generate Documents -> Document Review -> Sign -> Provision -> Onboard

The customer can track progress at any point in the journey.

## MVP
Build and demo in this order:

1. **Durable execution.** Complete the journey across sandbox systems, verify the final provisioning result, and recover from an interrupted write and a supported integration change.
2. **Risk assessment.** Run early, after business verification. Persist an overall tier, category scores, cited evidence, missing inputs, and recommended routing. Show the results in the admin review, including the applied risk policy version. High-risk cases require explicit review, and material evidence gaps pause the workflow for input.
3. **Customer and admin handoffs.** Support application, progress, missing-information submission, sandbox signing, and completed details. Give admins a review queue, action trace, and controls to resolve stalled runs.
4. **Guardrail adaptation.** Record review overrides and demonstrate approval of a versioned policy proposal using a minimal admin view.

Stretch, if time allows:
- Interactive risk map and future risk prediction
- Pricing recommendations and adjustments
- Customer cancellation and metrics dashboard
- Bank-side e-sign and field-level encryption

## Architecture

Customer 360 is a React frontend and a Python FastAPI backend that runs a LangGraph workflow. MongoDB Atlas holds all data, vector search indexes and agent memory. Gemini on Vertex AI is the LLM, and everything runs on Google Cloud.

| Layer | Technology | Role |
|---|---|---|
| Frontend | React + Vite + TypeScript | Customer site and admin site, with persona-based login redirect |
| API | FastAPI | Customer and admin endpoints (demo personas, no authentication), onboarding state, human review actions |
| Orchestration | LangGraph | The onboarding workflow: deterministic steps (state machine, review gates) combined with agentic steps. Supports durable execution, pause/resume and human-in-the-loop |
| Agents | LangChain `create_agent` | Risk, Compliance and Document agents, each with its own tools and prompt. Middleware is used for guardrails and retries |
| Data, retrieval and memory | MongoDB Atlas with `langchain-mongodb` | `MongoDBAtlasVectorSearch` and the hybrid (vector + full-text) retriever for regulations, procedures, documents, and verified prior outcomes and recovery examples. Run state and long-term memory are also stored in Atlas |
| LLM and embeddings | Gemini via `langchain[google-genai]` | Reasoning, extraction, document drafting |
| Observability | LangSmith | Tracing, debugging and evaluation of agent runs |
| Hosting | Google Cloud Run | Frontend and API containers |

**Design choices**
- LangChain agents are built on LangGraph, so persistence and human-in-the-loop come from the same layer.
- Deep Agents and LangSmith Fleet (no-code agents) are not used, because the workflow has fixed steps and needs fine-grained control.
- Guardrails are stored as versioned data in MongoDB and are updated only after human approval.
- Spring Boot is not used, to keep the build to one backend language and one service.
- The MongoDB checkpointer and long-term store must be confirmed in a short spike before the event. If unavailable, long-term memory falls back to a plain MongoDB collection.

## Repo and Development setup
- `frontend/` - React app. `backend/` - FastAPI app, agents and scripts (layout in BACKEND-PLAN.md). `docker-compose` or Cloud Run configs as needed.
- Configuration through environment variables (Mongo connection string, Google Cloud project, Gemini model names, LangSmith keys, `VITE_API_URL`). No secrets in the repository.
- Scripts: seed data, ingest regulations and procedures, create vector and full-text indexes.

## MongoDB Atlas
- Collections and indexes are listed in BACKEND-PLAN.md.
- Prioritize Vector Search on `agent_memory` for verified risk precedents and recovery examples. Filter by relevant metadata such as integration, contract version, product, and sector. See the backend plan for reference-data indexes.

## Security and compliance
- Use synthetic data only, with no real customer information.
- There is no authentication in the demo. Endpoints are open, so the app must never be deployed with real data.
- Plan PII handling, with field-level encryption as a stretch goal.
- Keep an immutable audit log of agent actions and human decisions.
- Add prompt-injection guardrails for uploaded documents.
- Require evidence and citations for risk and compliance findings. Agents run approved tools within the active policy, and humans decide at bank review gates.
- Name the Canadian regulations in the knowledge base: FINTRAC, PCMLTFA, PIPEDA, and OSFI guidance.

## Demo and seed data
Seed a low-risk business, a high-risk business, and a business with missing documents. Demonstrate:

1. Progress the low-risk application through verification, cited risk assessment, review, and signature.
2. Interrupt provisioning after the sandbox system commits but before the workflow records success. Restart and show the agent finding the existing account by operation ID, verifying it, and completing onboarding with one account.
3. Change a supported sandbox field mapping. Show the agent retrieving a prior recovery example, checking the revised contract, and proceeding once the effect can be verified.
4. Show the different routing and evidence for the high-risk and missing-document cases. Use a recorded override for the guardrail approval demo.
