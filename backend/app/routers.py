"""Customer and bank employee APIs for the sandbox onboarding workflow."""

import asyncio
import logging
import re
import os
from hashlib import sha256
from datetime import date, datetime, time, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from .mcp_database import MCPBucket, MCPDatabase as Database
from .reference_search import REFERENCE_FIELDS, SCOPE, retrieve_references
from .workflow_agents import AgreementDraft, ApplicationValidation, FinalAssessment, cited_sources, run_skill

from .agreement_terms import pricing_schedule, render_schedule
from .demo import customer_scope, _upsert_by_key, conversation_actor, ensure_demo_profile, get_actor, get_database, object_id
from .documents import document_response, store_upload, stream_document
from .workflow import GATES, REQUIRED_DOCUMENTS, RISK_POLICY, STEPS, TERMINAL, SIGNED_WORKFLOW, SIGNED_STATES, case_status, now, progress, transition, uses_signed_workflow, workflow_steps

logger = logging.getLogger(__name__)

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
        query.update(customer_scope(customer_id))
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


async def validate_application(application: dict):
    placeholders = {
        "i dont know", "dont know", "i do not know", "do not know", "unknown",
        "not sure", "unsure", "tbd", "n a", "na", "none", "test", "idk", "no idea",
    }
    issues = []
    for field, value in application.items():
        normalized = re.sub(r"[^\w]+", " ", value.casefold().replace("’", "").replace("'", "")).strip()
        if not normalized or normalized in placeholders:
            issues.append({"field": field, "message": "Enter a valid value for this field."})
    if not any(issue["field"] == "products" for issue in issues):
        try:
            pricing_schedule(application["products"])
        except ValueError as error:
            issues.append({"field": "products", "message": str(error)})
    if not issues and os.getenv("ONBOARDING_CHAT_MODEL"):
        result, _ = await agent_result("application-validation", ApplicationValidation, {"application": application})
        issues = [issue.model_dump() for issue in result.issues]
    if issues:
        raise HTTPException(422, {"message": "Invalid application values.", "fields": issues})


@router.post("/customer/onboardings", status_code=201)
async def start_application(payload: Application, database: Db, actor: Customer):
    customer_id, user_id = actor
    client_id = str(payload.conversationId or payload.id)
    application = payload.model_dump(exclude={"id", "conversationId"})
    lookup = {"client_id": client_id, **customer_scope(customer_id)}
    record = await database.onboardings.find_one(lookup)
    if record and record.get("discarding"):
        raise HTTPException(409, "This draft is being discarded.")
    if payload.conversationId and record is None:
        raise HTTPException(404, "Conversation draft not found.")

    if record is None or record["status"] == "DRAFT":
        await validate_application(application)
        fields = {
            "status": "APPLIED", "workflow": SIGNED_WORKFLOW, "stage": 0, "revision": 0, "application": application,
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
            await database.onboardings.upsert({"client_id": client_id, "customer_id": customer_id}, {
                **fields, "created_at": now(), "created_by": user_id,
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
        **customer_scope(actor[0]), "status": {"$ne": "DRAFT"},
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
            "coverNote": packet.get("cover_note"), "pricing": packet.get("pricing"),
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
    if uses_signed_workflow(record) and record["stage"] == 5:
        raise HTTPException(409, "Wait for the bank to reopen the application before uploading evidence.")
    return await store_upload(database, record["customer_id"], record["_id"], file)


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
    if uses_signed_workflow(record):
        if status != "AWAITING_SIGNATURE" or not record.get("documents_released"):
            raise HTTPException(409, "This application is not ready to sign.")
        packet = await released_agreement(database, record)
        signature = await database.sandbox_signatures.upsert({"_id": record["_id"]}, {
            "signer": payload.signer, "signed_at": now(), "actor_id": actor[1],
            "digest": packet["digest"], "template_version": packet["template_version"],
        })
        if signature["signer"] != payload.signer or signature.get("digest") != packet["digest"]:
            raise HTTPException(409, "A different signature already exists.")
        if record.get("agreement_signed"):
            return progress(record)
        return progress(await change(
            database, record, {"agreement_signed": True}, actor[1], "customer", "sign",
        ))
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


async def released_agreement(database, record):
    packet = await database.sandbox_documents.find_one({"_id": record["_id"]})
    if not packet or not packet.get("digest") or packet["digest"] != record.get("released_digest"):
        raise HTTPException(409, "The released agreement could not be verified.")
    if sha256(packet["content"].encode()).hexdigest() != packet["digest"]:
        raise HTTPException(409, "The released agreement content does not match its version.")
    return packet


async def checked_signature(database, record):
    packet = await released_agreement(database, record)
    signature = await database.sandbox_signatures.find_one({"_id": record["_id"]})
    if not signature or signature.get("digest") != packet["digest"] or signature.get("template_version") != packet["template_version"]:
        raise HTTPException(409, "The signature does not match the released agreement.")
    return signature


@router.post("/customer/onboardings/{onboarding_id}/return-agreement")
async def return_agreement(onboarding_id: str, database: Db, actor: Customer):
    record = await case(database, onboarding_id, actor[0])
    if not uses_signed_workflow(record):
        raise HTTPException(409, "This application uses the original signing flow.")
    if record.get("agreement_returned"):
        return progress(record)
    if case_status(record) != "AWAITING_SIGNATURE" or not record.get("agreement_signed"):
        raise HTTPException(409, "Sign the released agreement before returning it.")
    await checked_signature(database, record)
    return progress(await change(database, record, {
        "agreement_returned": True, "stage": 4, "status": "VERIFYING",
        "current_step": workflow_steps(record)[4],
    }, actor[1], "customer", "return_signed_agreement"))


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
    return {**progress(row), "riskTier": (row.get("risk") or {}).get("tier")}


@router.get("/admin/onboardings")
async def admin_cases(database: Db, actor: Admin, status: str | None = None,
                risk: str | None = None, sector: str | None = None, since: date | None = None):
    query = {"status": {"$ne": "DRAFT"}}
    if risk:
        query["risk.tier"] = risk
    if sector:
        query["application.sector"] = sector
    if since:
        query["submitted_at"] = {"$gte": datetime.combine(since, time.min, tzinfo=timezone.utc)}
    records = await database.onboardings.find(query, sort=("updated_at", -1))
    return [admin_progress(row) for row in records if not status or case_status(row) == status]


@router.get("/admin/reviews")
async def review_queue(database: Db, actor: Admin):
    return [admin_progress(row) for row in await database.onboardings.find({
        "status": "ADMIN_REVIEW", "$or": [
            {"workflow": SIGNED_WORKFLOW, "stage": {"$in": [2, 5]}},
            {"workflow": {"$ne": SIGNED_WORKFLOW}, "stage": {"$in": list(GATES)}},
        ],
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
        **admin_progress(record), "risk": record.get("risk"), "verification": record.get("verification"),
        "documents": await case_documents(database, record, admin=True), "history": history,
        "actions": await action_trace(database, record),
        "checkpoint": {"step": workflow_steps(record)[record["stage"]], "revision": record["revision"]},
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
    if uses_signed_workflow(record):
        return await signed_workflow_review(database, record, payload, actor)
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
        "status": case_status(record), "currentNode": workflow_steps(record)[record["stage"]],
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


async def agent_result(skill, schema, context, references=None):
    try:
        report = await run_in_threadpool(run_skill, skill, schema, context)
        return report, cited_sources(report, references) if references is not None else []
    except Exception as error:
        logger.warning("Workflow agent %s failed (%s)", skill, type(error).__name__)
        raise HTTPException(503, "The workflow agent could not complete this step. Check the model setup and retry.") from None


async def prepare_agreement(database, record):
    packet = await database.sandbox_documents.find_one({"_id": record["_id"]})
    if packet:
        if not packet.get("digest"):
            raise HTTPException(409, "An incompatible agreement already exists for this application.")
        return
    application = {key: record["application"][key] for key in ("businessName", "registration", "products")}
    try:
        pricing = pricing_schedule(application["products"])
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    draft, _ = await agent_result("document-generation", AgreementDraft, {"application": application})
    if draft.missingFields:
        raise HTTPException(422, "Agreement fields need review: " + ", ".join(draft.missingFields))
    content = (
        "Customer 360 sandbox business banking agreement\n"
        "Template version: 2\n"
        f"Application: {record['_id']}\n\n"
        f"Legal business name: {application['businessName']}\n"
        f"Registration: {application['registration']}\n"
        f"Requested products: {application['products']}\n\n"
        f"{render_schedule(pricing)}\n\n"
        "Billing and acceptance\n"
        "All amounts are Canadian dollars. Deposit and payment fees apply from service activation.\n"
        "Review this schedule before accepting. Activation follows final bank approval.\n\n"
        "These fictional rates and terms apply only to this sandbox. Signing creates no real banking or legal obligation.\n"
        "Use the onboarding workspace to record and return a sandbox signature.\n"
    )
    await sandbox_effect(database, record, "prepare-agreement", "sandbox_documents", {
        "content": content, "template_version": 2, "digest": sha256(content.encode()).hexdigest(),
        "pricing": pricing,
        "cover_note": draft.coverNote,
    })


async def review_references(database, record):
    vector_enabled = bool(os.getenv("VOYAGE_API_KEY"))
    if vector_enabled:
        application = record["application"]
        # Search with product and case topics; keep names and uploaded evidence out of Voyage inputs.
        query = (
            "Canadian corporate business banking onboarding: identity and registration verification, "
            "beneficial ownership evidence, privacy, signed agreement and risk scoring. "
            f"Sector: {application['sector'][:120]}. Products: {application['products'][:120]}."
        )
        try:
            return await retrieve_references(database, query), "atlas_vector_search"
        except Exception as error:
            logger.warning("Reference vector search failed (%s)", type(error).__name__)
            raise HTTPException(503, "Reference vector search failed. Check the Voyage key and Atlas indexes.") from None
    regulations, procedures = await asyncio.gather(
        database.regulations.find(SCOPE, projection=dict.fromkeys(REFERENCE_FIELDS, 1)),
        database.procedures.find(SCOPE, projection=dict.fromkeys(REFERENCE_FIELDS, 1)),
    )
    return [*regulations, *procedures], "reference_corpus"


async def final_reports(database, record, actor):
    signature = await checked_signature(database, record)
    (references, retrieval), documents, policy = await asyncio.gather(
        review_references(database, record),
        database.documents.find({"onboarding_id": record["_id"], "source": "uploaded"}),
        risk_policy(database, actor),
    )
    if not references or {source["kind"] for source in references} <= {"demo_bank_policy"} or not any(
        source["kind"] == "demo_bank_policy" for source in references
    ):
        raise HTTPException(409, "Load the Canadian regulatory references and bank procedures before running verification.")
    async def read_evidence(document):
        item = {"id": str(document["_id"]), "filename": document["filename"]}
        if document["content_type"] == "text/plain" and document["size_bytes"] <= 12000:
            content = await MCPBucket(database).read(document["storage_id"])
            item["text"] = content.decode("utf-8", errors="replace")
        return item

    evidence = await asyncio.gather(*(read_evidence(document) for document in documents))
    context = {
        "application": record["application"], "responses": record.get("information_responses", []),
        "signed_agreement": {"digest": signature["digest"], "template_version": signature["template_version"]},
        "uploaded_evidence": evidence,
        "references": [
            {key: source[key] for key in ("_id", "kind", "citation", "text", "version")}
            for source in references
        ],
        "bank_policy": policy,
    }
    assessment, _ = await agent_result("risk-assessment", FinalAssessment, {
        **context,
        "task": "First verify the evidence against the supplied requirements. Then use the verification findings and gaps to draft the final bank risk recommendation.",
    })
    verification, risk = assessment.verification, assessment.risk
    try:
        sources = cited_sources(verification, references)
        citations = cited_sources(risk, references)
    except ValueError:
        raise HTTPException(503, "The workflow agent returned an unknown reference. Retry the assessment.") from None
    verified = {
        **verification.model_dump(), "sources": sources,
        "agreementDigest": signature["digest"], "retrieval": retrieval,
    }
    highest = max(risk.ownership, risk.activity, risk.geography)
    return {
        "verification": verified,
        "risk": {
            **risk.model_dump(), "tier": "high" if highest >= 4 else "medium" if highest == 3 else "low",
            "missingInputs": list(dict.fromkeys([*verification.missingInputs, *risk.missingInputs])),
            "evidence": [source["citation"] for source in citations],
            "sources": citations, "policyVersion": policy["version"], "source": "agent", "reviewedAt": now(),
        },
    }


async def signed_workflow_review(database, record, payload, actor):
    stage = record["stage"]
    status = case_status(record)
    comments = payload.comments.strip()
    if payload.risk is not None:
        raise HTTPException(422, "Final risk is generated from the returned agreement and case evidence.")
    if status in TERMINAL:
        raise HTTPException(409, "This onboarding is closed.")
    if payload.decision == "cancel":
        if not comments:
            raise HTTPException(422, "Enter the reason for rejecting this application.")
        return admin_progress(await change(database, record, {"status": "CANCELLED", "rejected": True}, actor, "admin", "reject", comments))
    if payload.decision != "continue" or status == "PAUSED":
        updates = transition(record, payload.decision, comments)
        if updates["status"] == "NEEDS_INFO" and stage == 5:
            updates.update({
                "stage": 4, "resume_status": "VERIFYING", "current_step": workflow_steps(record)[4],
                "risk": None, "verification": None,
            })
        return admin_progress(await change(database, record, updates, actor, "admin", payload.decision, comments))
    if status != SIGNED_STATES[stage] or stage == 3:
        raise HTTPException(409, "This action is unavailable at the current step.")

    updates = {"status": SIGNED_STATES[stage + 1], "stage": stage + 1, "current_step": workflow_steps(record)[stage + 1]}
    if stage == 1:
        await prepare_agreement(database, record)
    elif stage == 2:
        packet = await database.sandbox_documents.find_one({"_id": record["_id"]})
        if not packet or not packet.get("digest"):
            raise HTTPException(409, "Prepare the agreement before releasing it.")
        updates.update({"documents_released": True, "released_digest": packet["digest"]})
    elif stage == 4:
        if not record.get("agreement_returned"):
            raise HTTPException(409, "The customer must return the signed agreement first.")
        updates.update(await final_reports(database, record, actor))
    elif stage == 5:
        if not comments:
            raise HTTPException(422, "Enter the reason for approving this application.")
        if not record.get("risk") or record["risk"]["missingInputs"]:
            raise HTTPException(422, "Resolve the material evidence gaps before approval.")
        signature = await checked_signature(database, record)
        if (record.get("verification") or {}).get("agreementDigest") != signature["digest"]:
            raise HTTPException(409, "Verify the returned agreement before approval.")
        await sandbox_effect(database, record, "provision", "sandbox_accounts", {
            "reference": f"DEMO-{str(record['_id']).upper()}", "status": "active", "signer": signature["signer"],
        })
    action = {1: "generate_agreement", 2: "release_agreement", 4: "verify_and_assess", 5: "approve"}.get(stage, "continue")
    return admin_progress(await change(database, record, updates, actor, "admin", action, comments))
