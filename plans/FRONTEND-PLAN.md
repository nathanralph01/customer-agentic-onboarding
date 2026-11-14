## Frontend Implementation

React + Vite + TypeScript + shadcn/ui + Tailwind CSS. React Router for navigation, a data-fetching library with polling (for example TanStack Query) for agent status, a component library for consistent UI, and a chart library if needed for the stretch risk map. The API base URL comes from an environment variable (`VITE_API_URL`). Features marked (Stretch) are built only if time allows. See PLAN.md for the MVP definition and BACKEND-PLAN.md for the endpoints.

### General behaviour
- Agent steps are asynchronous. Pages that show onboarding status poll the backend every few seconds, and show progress, loading and error states. Progress reflects persisted workflow state. Show customer actions directly on the onboarding page. Admins can see failures, actions awaiting verification, and the retry control.
- Keep the UI simple and accessible: labelled form fields, keyboard navigation, sufficient contrast, plain language for customers.
- Types for API responses are shared in one place, matching the backend schemas.

### Login Portal (persona picker, no authentication)
- The portal lists the seeded personas from `GET /demo/users` (customers and bank employees). Selecting one redirects to the customer site or admin site according to its role.
- The selected persona is kept in app state and sent as `customer_id` (customer calls) or `admin_id` (admin calls). There are no passwords or tokens.
- A persona switcher is always visible in the header so the demo can move quickly between customer and admin.

### Theme
The UI theme must be visually pleasing, and implement a cool truthworthy blue.
Palette: blue as the primary colour, a neutral grey or white background, and red, amber and green reserved for risk levels and status only. Don't rely on colour alone for risk. Add labels or icons so the risk map stays accessible, which the frontend plan already asks for.


### Customer facing site
Simple and accessible. Features:

**Feature #1 (MVP): Start onboarding.** A short multi-step form collects business details, owners, and products requested. On submit, the customer sees the onboarding id and the list of required documents returned by the backend.

**Feature #2 (MVP): Track onboarding.** Shows the current step, steps completed and remaining, estimated completion time, and the contact details of the team responsible for the current step. A progress stepper covers Apply, Verify, Risk, Compliance, Risk Review, Documents, Document Review, Sign, Provision, Onboard.

**Feature #3 (MVP): Provide information and documents.** When the status is "needs information" (or required documents are listed), the customer sees what is requested and can upload documents or answer questions. A documents list shows uploaded and generated documents with download.

**Feature #4 (MVP): E-sign.** When documents are ready, the customer sees them and a "Sign" button. The sandbox signature resumes the agent run. The progress view shows provisioning until the agent verifies the resulting account.

**Feature #5 (MVP): View completed onboarding details.** Summary of the finished onboarding: account status, benefits, access, and documents.


**Feature #6 (Stretch): Cancel onboarding.** A cancel button with a confirmation dialog, available at any non-final step.

### Admin facing site
Employees maintain customer profiles and step in when needed. Features:

**Feature #1 (MVP): Onboarding list and detail.** A filterable list (status, risk level, date, sector) of in-progress and completed onboardings. The detail page shows the application, state history, documents, audit trail, and an agent trace with action state, target references, verification evidence, and any recovery or escalation. Show the last checkpoint and let admins retry a recoverable run.

**Feature #2 (MVP): Review queue and decision.** A queue of onboardings waiting at a review gate. There are two gates: after Risk + Compliance, and after Document generation before releasing generated documents to the customer. Highlight cases that require an explicit high-risk decision. The reviewer can read the agent output with citations, add comments, edit where allowed, and choose Continue, Pause, Request information, or Cancel. Edits are recorded as overrides.

**Feature #3 (MVP priority): Risk assessment.** Put the overall risk tier and per-category scores in the onboarding detail and review queue workflow. Show cited evidence, missing inputs, the applicable policy version, and why the agent routed the case for review or more information.
- (Stretch) Interactive risk map and a future-risk trend with rationale.

**Feature #4 (Stretch): Pricing.** Show the agent recommendation and allow an admin to adjust it with a reason. Display the original and adjusted values.

**Feature #5 (Stretch): E-sign.** Mock "Sign" button for the bank side, if needed.

**Feature #6 (MVP): Guardrails.** A page with the active guardrails and version history, and a list of guardrail proposals generated from admin overrides. Each proposal shows the overrides that led to it, and the admin can approve or reject it. This demonstrates the system adapting its guardrails with human approval.

**Feature #7 (Stretch): Metrics.** A small dashboard: average time to onboard, count by state, and agent override rate. Use it to show the before and after improvement in the demo.
