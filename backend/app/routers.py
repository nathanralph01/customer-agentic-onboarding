"""Customer and bank employee APIs for the sandbox onboarding workflow."""

from datetime import date, datetime, time, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from .mcp_database import MCPDatabase as Database

from .demo import _upsert_by_key, conversation_actor, ensure_demo_profile, get_actor, get_database, object_id
from .documents import document_response, store_upload, stream_document
from .workflow import GATES, REQUIRED_DOCUMENTS, RISK_POLICY, STEPS, TERMINAL, case_status, now, progress, transition

router = APIRouter(prefix="/api/v1")
Db = Annotated[Database, Depends(get_database)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Application(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: UUID
    conversationId: UUID | None = None
    businessName: Text
    businessActivity: Text
    registration: Text
    owners: Text
    products: Text
    sector: Text


class Risk(BaseModel):
    tier: Literal["low", "medium", "high"]
    rationale: Text
    evidence: list[Text] = Field(min_length=1, max_length=10)
    missingInputs: list[Text] = Field(default_factory=list, max_length=10)
    ownership: int = Field(ge=1, le=5)
    activity: int = Field(ge=1, le=5)
    geography: int = Field(ge=1, le=5)


class Review(BaseModel):
    revision: int = Field(ge=0)
    decision: Literal["continue", "pause", "cancel", "request_info"]
    comments: str = Field(default="", max_length=4000)
    risk: Risk | None = None


class Information(BaseModel):
    response: Text


class Signature(BaseModel):
    signer: Text


class ProposalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comments: Text


async def customer_actor(database: Db, customer_id: str):
    return await conversation_actor(database, customer_id)


async def admin_actor(database: Db, admin_id: str | None = None):
    return await get_actor(database, "admin", admin_id)


Customer = Annotated[tuple[ObjectId, ObjectId], Depends(customer_actor)]
Admin = Annotated[ObjectId, Depends(admin_actor)]


@router.get("/demo/users")
async def personas(database: Db):
    customer_id, user_id = await ensure_demo_profile(database)
    admin = await _upsert_by_key(database.users, {"email": "reviewer.demo@customer360.example"}, {
        "name": "Morgan Lee", "role": "admin", "email": "reviewer.demo@customer360.example", "created_at": now(),
    })
    customer = await database.users.find_one({"_id": user_id})
    return [
        {"id": str(user_id), "customerId": str(customer_id), "name": customer["name"], "role": "customer"},
        {"id": str(admin["_id"]), "customerId": None, "name": admin["name"], "role": "admin"},
    ]


async def case(database, onboarding_id, customer_id=None):
    query = {"_id": object_id(onboarding_id), "status": {"$ne": "DRAFT"}}
    if customer_id is not None:
        query["customer_id"] = customer_id
    record = await database.onboardings.find_one(query)
    if record is None:
        raise HTTPException(404, "Onboarding not found.")
    return record


def audit_event(record, actor, role, action, previous, comments):
    return {
        "actor_id": str(actor), "role": role, "action": action, "from": previous,
        "to": case_status(record), "stage": record["stage"], "reason": comments,
        "created_at": now(),
    }


async def change(database, record, updates, actor, role, action, comments="", override=None):
    event = audit_event({**record, **updates}, actor, role, action, case_status(record), comments)
    push = {"audit_history": event}
    if override:
        push["risk_overrides"] = override
    query = {"_id": record["_id"], "revision": record["revision"]}
    transition_id = str(uuid4())
    await database.onboardings.update_one(query, {
        "$set": {**updates, "last_transition": transition_id, "updated_at": event["created_at"]},
        "$inc": {"revision": 1}, "$push": push,
    })
    updated = await database.onboardings.find_one({"_id": record["_id"]})
    if not updated or updated.get("last_transition") != transition_id:
        raise HTTPException(409, "This application changed. Reload and try again.")
    return updated


@router.post("/customer/onboardings", status_code=201)
async def start_application(payload: Application, database: Db, actor: Customer):
    customer_id, user_id = actor
    client_id = str(payload.conversationId or payload.id)
    application = payload.model_dump(exclude={"id", "conversationId"})
    lookup = {"customer_id": customer_id, "client_id": client_id}
    record = await database.onboardings.find_one(lookup)
    if payload.conversationId and record is None:
        raise HTTPException(404, "Conversation draft not found.")

    if record is None or record["status"] == "DRAFT":
        fields = {
            "status": "APPLIED", "stage": 0, "revision": 0, "application": application,
            "required_documents": list(REQUIRED_DOCUMENTS),
            "requested_products": [item.strip() for item in payload.products.split(",") if item.strip()],
            "submitted_at": now(), "updated_at": now(), "current_step": STEPS[0],
        }
        fields["audit_history"] = [audit_event(
            fields, user_id, "customer", "submit", "DRAFT" if record else None, "",
        )]
        if record:
            await database.onboardings.update_one(
                {"_id": record["_id"], "status": "DRAFT"}, {"$set": fields},
            )
        else:
            await database.onboardings.upsert(lookup, {
                **lookup, **fields, "created_at": now(), "created_by": user_id,
            })
        record = await database.onboardings.find_one(lookup)
    if record is None or record.get("application") != application:
        raise HTTPException(409, "This draft has already been submitted.")
    if payload.conversationId:
        await database.conversations.update_one(lookup, {"$set": {"application_submitted": True}})
    return progress(record)


@router.get("/customer/onboardings")
async def customer_cases(database: Db, actor: Customer):
    return [progress(row) for row in await database.onboardings.find({
        "customer_id": actor[0], "status": {"$ne": "DRAFT"},
    }, sort=("updated_at", -1))]


@router.get("/customer/onboardings/{onboarding_id}")
async def customer_case(onboarding_id: str, database: Db, actor: Customer):
    return progress(await case(database, onboarding_id, actor[0]))


async def case_documents(database, record, admin=False):
    documents = [document_response(doc) for doc in await database.documents.find({
        "onboarding_id": record["_id"], "source": {"$ne": "generated"},
    }, sort=("created_at", 1))]
    packet = await database.sandbox_documents.find_one({"_id": record["_id"]})
    if packet and (admin or record.get("documents_released")):
        documents.append({
            "id": str(packet["_id"]), "filename": "Sandbox banking agreement.txt",
            "contentType": "text/plain", "sizeBytes": len(packet["content"].encode()),
            "createdAt": packet["created_at"].isoformat(), "source": "generated",
        })
    return documents


@router.get("/customer/onboardings/{onboarding_id}/documents")
async def customer_documents(onboarding_id: str, database: Db, actor: Customer):
    return await case_documents(database, await case(database, onboarding_id, actor[0]))


@router.post("/customer/onboardings/{onboarding_id}/documents", status_code=201)
async def upload_case_document(onboarding_id: str, database: Db, actor: Customer, file: UploadFile = File(...)):
    record = await case(database, onboarding_id, actor[0])
    if case_status(record) in TERMINAL:
        raise HTTPException(409, "This onboarding no longer accepts uploads.")
    return await store_upload(database, actor[0], record["_id"], file)


async def download_case_document(database, record, document_id, admin=False):
    if document_id == str(record["_id"]) and (admin or record.get("documents_released")):
        packet = await database.sandbox_documents.find_one({"_id": record["_id"]})
        if packet:
            return Response(packet["content"], media_type="text/plain", headers={
                "Content-Disposition": 'attachment; filename="sandbox-banking-agreement.txt"',
            })
    document = await database.documents.find_one({
        "_id": object_id(document_id), "onboarding_id": record["_id"], "source": {"$ne": "generated"},
    })
    if document is None:
        raise HTTPException(404, "Document not found.")
    return await stream_document(database, document)


@router.get("/customer/onboardings/{onboarding_id}/documents/{document_id}")
async def customer_download(onboarding_id: str, document_id: str, database: Db, actor: Customer):
    return await download_case_document(database, await case(database, onboarding_id, actor[0]), document_id)


@router.post("/customer/onboardings/{onboarding_id}/information")
async def supply_information(onboarding_id: str, payload: Information, database: Db, actor: Customer):
    record = await case(database, onboarding_id, actor[0])
    if record["status"] != "NEEDS_INFO":
        raise HTTPException(409, "This application has no open information request.")
    responses = [*record.get("information_responses", []), {
        "request": record["requested_information"], "response": payload.response, "createdAt": now(),
    }]
    updated = await change(database, record, {
        "status": record["resume_status"], "information_responses": responses,
    }, actor[1], "customer", "supply_information")
    return progress(updated)


@router.post("/customer/onboardings/{onboarding_id}/sign")
async def sign(onboarding_id: str, payload: Signature, database: Db, actor: Customer):
    record = await case(database, onboarding_id, actor[0])
    status = case_status(record)
    if status in {"PROVISIONING", "ONBOARDED"}:
        signature = await database.sandbox_signatures.find_one({"_id": record["_id"]})
        if signature and signature["signer"] == payload.signer:
            return progress(record)
    if status != "AWAITING_SIGNATURE" or not record.get("documents_released"):
        raise HTTPException(409, "This application is not ready to sign.")

    signature = await database.sandbox_signatures.upsert({"_id": record["_id"]}, {
        "_id": record["_id"], "signer": payload.signer, "signed_at": now(), "actor_id": actor[1],
    })
    if signature["signer"] != payload.signer:
        raise HTTPException(409, "This agreement is already signed.")
    return progress(await change(
        database, record, {"stage": 8, "current_step": STEPS[8]}, actor[1], "customer", "sign",
    ))


@router.get("/customer/onboardings/{onboarding_id}/summary")
async def summary(onboarding_id: str, database: Db, actor: Customer):
    record = await case(database, onboarding_id, actor[0])
    account = await database.sandbox_accounts.find_one({"_id": record["_id"]})
    if record["status"] != "ONBOARDED" or not account:
        raise HTTPException(409, "The sandbox account is still pending.")
    return {
        "accountReference": account["reference"], "status": account["status"],
        "products": record["requested_products"], "benefits": ["Business banking onboarding completed"],
        "access": "Sandbox account. Contact Customer Onboarding for the demo walkthrough.",
        "documents": await case_documents(database, record),
    }


def admin_progress(row):
    return {**progress(row), "riskTier": row.get("risk", {}).get("tier")}


@router.get("/admin/onboardings")
async def admin_cases(database: Db, actor: Admin, status: str | None = None,
                risk: str | None = None, sector: str | None = None, since: date | None = None):
    query = {"status": {"$ne": "DRAFT"}}
    if risk:
        query["risk.tier"] = risk
    if sector:
        query["application.sector"] = sector
    if since:
        from datetime import date, datetime, time, timezonetime, time, timezone
        query["submitted_at"] = {"$gte": datetime.combine(since, time.min, tzinfo=timezone.utc)}
    records = await database.onboardings.find(query, sort=("updated_at", -1))
    return [admin_progress(row) for row in records if not status or case_status(row) == status]


@router.get("/admin/reviews")
async def review_queue(database: Db, actor: Admin):
    return [admin_progress(row) for row in await database.onboardings.find({
        "status": "ADMIN_REVIEW", "stage": {"$in": list(GATES)},
    }, sort=("updated_at", -1))]


async def action_trace(database, record):
    actions = await database.workflow_actions.find(
        {"onboarding_id": str(record["_id"])}, sort=("created_at", 1),
    )
    return [{**row, "id": row["_id"]} for row in actions]


@router.get("/admin/onboardings/{onboarding_id}")
async def admin_case(onboarding_id: str, database: Db, actor: Admin):
    record = await case(database, onboarding_id)
    history = await database.audit_log.find(
        {"onboarding_id": record["_id"]}, projection={"onboarding_id": 0}, sort=("created_at", 1),
    )
    for event in history:
        event.pop("_id", None)
    history.extend(record.get("audit_history", []))
    history.sort(key=lambda event: event["created_at"])
    return {
        **admin_progress(record), "risk": record.get("risk"),
        "documents": await case_documents(database, record, admin=True), "history": history,
        "actions": await action_trace(database, record),
        "checkpoint": {"step": STEPS[record["stage"]], "revision": record["revision"]},
    }


@router.get("/admin/onboardings/{onboarding_id}/documents/{document_id}")
async def admin_download(onboarding_id: str, document_id: str, database: Db, actor: Admin):
    return await download_case_document(database, await case(database, onboarding_id), document_id, admin=True)


@router.get("/admin/onboardings/{onboarding_id}/risk")
async def risk_result(onboarding_id: str, database: Db, actor: Admin):
    return (await case(database, onboarding_id)).get("risk")


@router.get("/admin/risk-appetite")
async def risk_policy(database: Db, actor: Admin, sector: str | None = None, customer_type: str | None = None):
    guardrail = await database.guardrails.find_one({"_id": RISK_POLICY["key"]})
    return {
        **RISK_POLICY, "sector": sector, "customerType": customer_type,
        "version": guardrail["active_version"] if guardrail else RISK_POLICY["version"],
        "rule": guardrail["versions"][-1]["rule"] if guardrail else "High risk requires a documented reviewer decision.",
    }


async def sandbox_effect(database, record, key, target, expected):
    """Persist intent before dispatch and verify the separately stored record."""
    onboarding_id = str(record["_id"])
    operation = f"{onboarding_id}:{key}"
    await database.workflow_actions.upsert({"_id": operation}, {
        "onboarding_id": onboarding_id, "target": target, "state": "pending",
        "intent": expected, "created_at": now(),
    })
    await database[target].upsert({"_id": record["_id"]}, {
        **expected, "operation_id": operation, "created_at": now(),
    })
    observed = await database[target].find_one({"_id": record["_id"]})
    if observed is None or observed.get("operation_id") != operation or any(
        observed.get(field) != value for field, value in expected.items()
    ):
        await database.workflow_actions.update_one({"_id": operation}, {"$set": {"state": "conflict"}})
        raise HTTPException(409, "The sandbox record conflicts with the requested action.")
    await database.workflow_actions.update_one({"_id": operation}, {"$set": {
        "state": "verified", "reference": onboarding_id,
        "evidence": "Read back the sandbox record and matched the operation and expected fields.",
        "verified_at": now(),
    }})


async def perform_stage_action(database, record):
    stage = record["stage"]
    if stage == 1:
        await sandbox_effect(database, record, "verify", "sandbox_verifications", {
            "business_name": record["application"]["businessName"], "status": "reviewer_confirmed",
        })
    if stage == 5:
        await sandbox_effect(database, record, "prepare-agreement", "sandbox_documents", {
            "content": (
                f"Sandbox business banking agreement\n\n"
                f"Business: {record['application']['businessName']}\n"
                f"Products: {record['application']['products']}\n\n"
                "This agreement is for demonstration only and carries no legal effect."
            ),
        })
    if stage == 8:
        signature = await database.sandbox_signatures.find_one({"_id": record["_id"]})
        if signature is None:
            raise HTTPException(409, "A sandbox signature is required before provisioning.")
        await sandbox_effect(database, record, "provision", "sandbox_accounts", {
            "reference": f"DEMO-{str(record['_id']).upper()}",
            "status": "active", "signer": signature["signer"],
        })


@router.post("/admin/onboardings/{onboarding_id}/review")
async def review(onboarding_id: str, payload: Review, database: Db, actor: Admin):
    record = await case(database, onboarding_id)
    if record["revision"] != payload.revision:
        raise HTTPException(409, "This application changed. Reload and try again.")
    comments = payload.comments.strip()
    updates = transition(record, payload.decision, comments)
    if updates["status"] == "PROVISIONING":
        updates["status"] = "AWAITING_SIGNATURE"
    if "stage" in updates:
        updates["current_step"] = STEPS[updates["stage"]]

    starting_status = case_status(record)
    stage = record["stage"]
    risk = record.get("risk")
    if payload.risk:
        if stage not in {2, 4} or starting_status in {"PAUSED", "NEEDS_INFO"} or payload.decision == "cancel":
            raise HTTPException(409, "Risk can only be entered during risk assessment or risk review.")
        rule = await risk_policy(database, actor)
        risk = {
            **payload.risk.model_dump(), "policyVersion": rule["version"],
            "source": "bank_review", "reviewedAt": now(),
        }
        updates["risk"] = risk
    if payload.decision == "continue" and starting_status != "PAUSED":
        if stage in {2, 4} and not risk:
            raise HTTPException(422, "Record a risk assessment first.")
        if stage == 4 and risk["missingInputs"]:
            raise HTTPException(422, "Request the missing information or resolve it in the assessment before continuing.")
        if stage == 4 and risk["tier"] == "high" and not comments:
            raise HTTPException(422, "Record the reason for continuing with this risk assessment.")
        if stage in {1, 3, 6} and not comments:
            raise HTTPException(422, "Record what you reviewed before continuing.")
        if stage == 6:
            if not await database.sandbox_documents.find_one({"_id": record["_id"]}):
                raise HTTPException(409, "Prepare the agreement before releasing it.")
            updates["documents_released"] = True

    override = None
    if payload.risk and record.get("risk"):
        if not comments:
            raise HTTPException(422, "Explain why the recorded risk assessment is changing.")
        override = {
            "id": str(ObjectId()), "before": record["risk"], "after": risk,
            "reason": comments, "actor_id": str(actor), "created_at": now(),
        }
    if payload.decision == "continue" and starting_status != "PAUSED" and stage in {1, 5, 8}:
        await perform_stage_action(database, record)
    updated = await change(database, record, updates, actor, "admin", payload.decision, comments, override)
    return admin_progress(updated)


@router.get("/admin/workflow/runs/{onboarding_id}")
async def workflow_run(onboarding_id: str, database: Db, actor: Admin):
    record = await case(database, onboarding_id)
    return {
        "status": case_status(record), "currentNode": STEPS[record["stage"]],
        "checkpoint": record["revision"], "actions": await action_trace(database, record),
    }


@router.post("/admin/workflow/runs/{onboarding_id}/retry")
async def retry_workflow(onboarding_id: str, database: Db, actor: Admin):
    record = await case(database, onboarding_id)
    if case_status(record) not in {"VERIFYING", "DOCUMENT_GENERATION", "PROVISIONING"}:
        raise HTTPException(409, "There is no sandbox action to retry at this step.")
    return await review(onboarding_id, Review(
        revision=record["revision"], decision="continue", comments="Reconcile and retry sandbox action.",
    ), database, actor)


class Proposal(BaseModel):
    rule: Text
    onboardingId: str
    reason: Text


@router.get("/admin/guardrails")
async def guardrails(database: Db, actor: Admin):
    active = await database.guardrails.find_one({"_id": RISK_POLICY["key"]})
    if not active:
        return [{
            "key": RISK_POLICY["key"], "activeVersion": 1,
            "versions": [{"version": 1, "rule": "High risk requires a documented reviewer decision."}],
        }]
    return [{"key": active["_id"], "activeVersion": active["active_version"], "versions": active["versions"]}]


@router.get("/admin/guardrail-proposals")
async def proposals(database: Db, actor: Admin):
    return [
        {**row, "id": str(row.pop("_id"))}
        for row in await database.guardrail_proposals.find({}, projection={"actor_id": 0}, sort=("created_at", -1))
    ]


@router.post("/admin/guardrail-proposals", status_code=201)
async def propose(payload: Proposal, database: Db, actor: Admin):
    record = await case(database, payload.onboardingId)
    overrides = record.get("risk_overrides", [])
    legacy = await database.overrides.find({"onboarding_id": record["_id"]}, sort=("created_at", -1))
    override = overrides[-1] if overrides else legacy[0] if legacy else None
    if not override:
        raise HTTPException(422, "Record a risk override on this onboarding before proposing a guardrail.")
    result = await database.guardrail_proposals.insert_one({
        "rule": payload.rule, "reason": payload.reason, "status": "pending",
        "override": {"id": str(override.get("id") or override["_id"]), "reason": override["reason"], "caseId": payload.onboardingId},
        "actor_id": actor, "created_at": now(),
    })
    return {"id": str(result.inserted_id)}


@router.post("/admin/guardrail-proposals/{proposal_id}/decision")
async def decide_proposal(proposal_id: str, payload: ProposalDecision, database: Db, actor: Admin):
    key = object_id(proposal_id)

    proposal = await database.guardrail_proposals.find_one({"_id": key})
    if proposal is None or proposal["status"] != "pending":
        raise HTTPException(409, "This proposal is no longer pending.")
    policy_id = RISK_POLICY["key"]
    current = await database.guardrails.find_one({"_id": policy_id})
    versions = current["versions"] if current else [
        {"version": 1, "rule": "High risk requires a documented reviewer decision."}
    ]
    published = next((version for version in versions if version.get("proposalId") == proposal_id), None)
    if published and payload.decision == "reject":
        raise HTTPException(409, "This policy version has already been published. Retry approval.")
    if payload.decision == "approve" and not published:
        version = versions[-1]["version"] + 1
        fields = {
            "active_version": version,
            "versions": [*versions, {
                "version": version, "rule": proposal["rule"], "proposalId": proposal_id,
                "approvedBy": str(actor), "approvedAt": now(),
            }],
        }
        if current:
            await database.guardrails.update_one({"_id": policy_id}, {"$set": fields})
        else:
            await database.guardrails.upsert({"_id": policy_id}, fields)
    decision = "approved" if payload.decision == "approve" else "rejected"
    await database.guardrail_proposals.update_one({"_id": key, "status": "pending"}, {"$set": {
        "status": decision, "decisionReason": payload.comments,
        "decidedBy": str(actor), "decidedAt": now(),
    }})
    return {"status": decision}
