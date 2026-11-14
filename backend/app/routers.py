"""Customer and bank employee APIs for the sandbox onboarding workflow."""

from datetime import date, datetime, time, timezone
from typing import Annotated, Literal
from uuid import UUID

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

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


def customer_actor(database: Db, customer_id: str):
    return conversation_actor(database, customer_id)


def admin_actor(database: Db, admin_id: str | None = None):
    return get_actor(database, "admin", admin_id)


Customer = Annotated[tuple[ObjectId, ObjectId], Depends(customer_actor)]
Admin = Annotated[ObjectId, Depends(admin_actor)]


@router.get("/demo/users")
def personas(database: Db):
    customer_id, user_id = ensure_demo_profile(database)
    admin = _upsert_by_key(database.users, {"email": "reviewer.demo@customer360.example"}, {
        "name": "Morgan Lee", "role": "admin", "email": "reviewer.demo@customer360.example", "created_at": now(),
    })
    customer = database.users.find_one({"_id": user_id})
    return [
        {"id": str(user_id), "customerId": str(customer_id), "name": customer["name"], "role": "customer"},
        {"id": str(admin["_id"]), "customerId": None, "name": admin["name"], "role": "admin"},
    ]


def case(database, onboarding_id, customer_id=None):
    query = {"_id": object_id(onboarding_id), "status": {"$ne": "DRAFT"}}
    if customer_id is not None:
        query["customer_id"] = customer_id
    record = database.onboardings.find_one(query)
    if record is None:
        raise HTTPException(404, "Onboarding not found.")
    return record


def audit(database, session, record, actor, role, action, previous, comments):
    database.audit_log.insert_one({
        "onboarding_id": record["_id"], "actor_id": str(actor), "role": role,
        "action": action, "from": previous, "to": case_status(record),
        "stage": record["stage"], "reason": comments, "created_at": now(),
    }, session=session)


def change(database, session, record, updates, actor, role, action, comments=""):
    updated = database.onboardings.find_one_and_update(
        {"_id": record["_id"], "revision": record["revision"]},
        {"$set": {**updates, "updated_at": now()}, "$inc": {"revision": 1}},
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if updated is None:
        raise HTTPException(409, "This application changed. Reload and try again.")
    audit(database, session, updated, actor, role, action, case_status(record), comments)
    return updated


def transact(database, callback):
    with database.client.start_session() as session:
        return session.with_transaction(callback)


@router.post("/customer/onboardings", status_code=201)
def start_application(payload: Application, database: Db, actor: Customer):
    customer_id, user_id = actor
    client_id = str(payload.conversationId or payload.id)
    application = payload.model_dump(exclude={"id", "conversationId"})

    def submit(session):
        lookup = {"customer_id": customer_id, "client_id": client_id}
        record = database.onboardings.find_one(lookup, session=session)
        if record and record["status"] != "DRAFT":
            if record.get("application") == application:
                return progress(record)
            raise HTTPException(409, "This draft has already been submitted.")
        if payload.conversationId and record is None:
            raise HTTPException(404, "Conversation draft not found.")
        fields = {
            "status": "APPLIED", "stage": 0, "revision": 0, "application": application,
            "required_documents": list(REQUIRED_DOCUMENTS),
            "requested_products": [item.strip() for item in payload.products.split(",") if item.strip()],
            "submitted_at": now(), "updated_at": now(), "current_step": STEPS[0],
        }
        if record:
            query = {"_id": record["_id"], "status": "DRAFT"}
        else:
            query = lookup
        saved = database.onboardings.find_one_and_update(
            query, {"$set": fields, "$setOnInsert": {**lookup, "created_at": now(), "created_by": user_id}},
            upsert=record is None, return_document=ReturnDocument.AFTER, session=session,
        )
        if payload.conversationId:
            database.conversations.update_one(
                {"client_id": client_id, "customer_id": customer_id},
                {"$set": {"application_submitted": True}},
                session=session,
            )
        audit(database, session, saved, user_id, "customer", "submit", "DRAFT" if record else None, "")
        return progress(saved)

    try:
        return transact(database, submit)
    except DuplicateKeyError:
        existing = database.onboardings.find_one({"customer_id": customer_id, "client_id": client_id})
        if existing and existing.get("application") == application:
            return progress(existing)
        raise HTTPException(409, "Application ID is already in use.") from None


@router.get("/customer/onboardings")
def customer_cases(database: Db, actor: Customer):
    return [progress(row) for row in database.onboardings.find({
        "customer_id": actor[0], "status": {"$ne": "DRAFT"},
    }).sort("updated_at", -1)]


@router.get("/customer/onboardings/{onboarding_id}")
def customer_case(onboarding_id: str, database: Db, actor: Customer):
    return progress(case(database, onboarding_id, actor[0]))


def case_documents(database, record, admin=False):
    documents = [document_response(doc) for doc in database.documents.find({
        "onboarding_id": record["_id"], "source": {"$ne": "generated"},
    }).sort("created_at", 1)]
    packet = database.sandbox_documents.find_one({"_id": record["_id"]})
    if packet and (admin or record.get("documents_released")):
        documents.append({
            "id": str(packet["_id"]), "filename": "Sandbox banking agreement.txt",
            "contentType": "text/plain", "sizeBytes": len(packet["content"].encode()),
            "createdAt": packet["created_at"].isoformat(), "source": "generated",
        })
    return documents


@router.get("/customer/onboardings/{onboarding_id}/documents")
def customer_documents(onboarding_id: str, database: Db, actor: Customer):
    return case_documents(database, case(database, onboarding_id, actor[0]))


@router.post("/customer/onboardings/{onboarding_id}/documents", status_code=201)
def upload_case_document(onboarding_id: str, database: Db, actor: Customer, file: UploadFile = File(...)):
    record = case(database, onboarding_id, actor[0])
    if case_status(record) in TERMINAL:
        raise HTTPException(409, "This onboarding no longer accepts uploads.")
    return store_upload(database, actor[0], record["_id"], file)


def download_case_document(database, record, document_id, admin=False):
    if document_id == str(record["_id"]) and (admin or record.get("documents_released")):
        packet = database.sandbox_documents.find_one({"_id": record["_id"]})
        if packet:
            return Response(packet["content"], media_type="text/plain", headers={
                "Content-Disposition": 'attachment; filename="sandbox-banking-agreement.txt"',
            })
    document = database.documents.find_one({
        "_id": object_id(document_id), "onboarding_id": record["_id"], "source": {"$ne": "generated"},
    })
    if document is None:
        raise HTTPException(404, "Document not found.")
    return stream_document(database, document)


@router.get("/customer/onboardings/{onboarding_id}/documents/{document_id}")
def customer_download(onboarding_id: str, document_id: str, database: Db, actor: Customer):
    return download_case_document(database, case(database, onboarding_id, actor[0]), document_id)


@router.post("/customer/onboardings/{onboarding_id}/information")
def supply_information(onboarding_id: str, payload: Information, database: Db, actor: Customer):
    record = case(database, onboarding_id, actor[0])
    if record["status"] != "NEEDS_INFO":
        raise HTTPException(409, "This application has no open information request.")
    responses = [*record.get("information_responses", []), {
        "request": record["requested_information"], "response": payload.response, "createdAt": now(),
    }]
    updated = transact(database, lambda session: change(database, session, record, {
        "status": record["resume_status"], "information_responses": responses,
    }, actor[1], "customer", "supply_information"))
    return progress(updated)


@router.post("/customer/onboardings/{onboarding_id}/sign")
def sign(onboarding_id: str, payload: Signature, database: Db, actor: Customer):
    record = case(database, onboarding_id, actor[0])
    status = case_status(record)
    if status in {"PROVISIONING", "ONBOARDED"}:
        signature = database.sandbox_signatures.find_one({"_id": record["_id"]})
        if signature and signature["signer"] == payload.signer:
            return progress(record)
    if status != "AWAITING_SIGNATURE" or not record.get("documents_released"):
        raise HTTPException(409, "This application is not ready to sign.")

    def persist(session):
        database.sandbox_signatures.insert_one({
            "_id": record["_id"], "signer": payload.signer, "signed_at": now(), "actor_id": actor[1],
        }, session=session)
        return change(database, session, record, {"stage": 8, "current_step": STEPS[8]}, actor[1], "customer", "sign")

    try:
        return progress(transact(database, persist))
    except DuplicateKeyError:
        latest = case(database, onboarding_id, actor[0])
        signature = database.sandbox_signatures.find_one({"_id": record["_id"]})
        if signature and signature["signer"] == payload.signer and case_status(latest) in {"PROVISIONING", "ONBOARDED"}:
            return progress(latest)
        raise HTTPException(409, "This agreement is already signed.") from None


@router.get("/customer/onboardings/{onboarding_id}/summary")
def summary(onboarding_id: str, database: Db, actor: Customer):
    record = case(database, onboarding_id, actor[0])
    account = database.sandbox_accounts.find_one({"_id": record["_id"]})
    if record["status"] != "ONBOARDED" or not account:
        raise HTTPException(409, "The sandbox account is still pending.")
    return {
        "accountReference": account["reference"], "status": account["status"],
        "products": record["requested_products"], "benefits": ["Business banking onboarding completed"],
        "access": "Sandbox account. Contact Customer Onboarding for the demo walkthrough.",
        "documents": case_documents(database, record),
    }


def admin_progress(row):
    return {**progress(row), "riskTier": row.get("risk", {}).get("tier")}


@router.get("/admin/onboardings")
def admin_cases(database: Db, actor: Admin, status: str | None = None,
                risk: str | None = None, sector: str | None = None, since: date | None = None):
    query = {"status": {"$ne": "DRAFT"}}
    if risk:
        query["risk.tier"] = risk
    if sector:
        query["application.sector"] = sector
    if since:
        from datetime import date, datetime, time, timezonetime, time, timezone
        query["submitted_at"] = {"$gte": datetime.combine(since, time.min, tzinfo=timezone.utc)}
    records = database.onboardings.find(query).sort("updated_at", -1)
    return [admin_progress(row) for row in records if not status or case_status(row) == status]


@router.get("/admin/reviews")
def review_queue(database: Db, actor: Admin):
    return [admin_progress(row) for row in database.onboardings.find({
        "status": "ADMIN_REVIEW", "stage": {"$in": list(GATES)},
    }).sort("updated_at", -1)]


def action_trace(database, record):
    actions = database.workflow_actions.find(
        {"onboarding_id": str(record["_id"])}
    ).sort("created_at", 1)
    return [{**row, "id": row["_id"]} for row in actions]


@router.get("/admin/onboardings/{onboarding_id}")
def admin_case(onboarding_id: str, database: Db, actor: Admin):
    record = case(database, onboarding_id)
    history = list(database.audit_log.find(
        {"onboarding_id": record["_id"]}, {"_id": 0, "onboarding_id": 0},
    ).sort("created_at", 1))
    return {
        **admin_progress(record), "risk": record.get("risk"),
        "documents": case_documents(database, record, admin=True), "history": history,
        "actions": action_trace(database, record),
        "checkpoint": {"step": STEPS[record["stage"]], "revision": record["revision"]},
    }


@router.get("/admin/onboardings/{onboarding_id}/documents/{document_id}")
def admin_download(onboarding_id: str, document_id: str, database: Db, actor: Admin):
    return download_case_document(database, case(database, onboarding_id), document_id, admin=True)


@router.get("/admin/onboardings/{onboarding_id}/risk")
def risk_result(onboarding_id: str, database: Db, actor: Admin):
    return case(database, onboarding_id).get("risk")


@router.get("/admin/risk-appetite")
def risk_policy(database: Db, actor: Admin, sector: str | None = None, customer_type: str | None = None):
    guardrail = database.guardrails.find_one({"_id": RISK_POLICY["key"]})
    return {
        **RISK_POLICY, "sector": sector, "customerType": customer_type,
        "version": guardrail["active_version"] if guardrail else RISK_POLICY["version"],
        "rule": guardrail["versions"][-1]["rule"] if guardrail else "High risk requires a documented reviewer decision.",
    }


def sandbox_effect(database, record, key, target, expected):
    """Persist intent before dispatch and verify the separately stored record."""
    onboarding_id = str(record["_id"])
    operation = f"{onboarding_id}:{key}"
    database.workflow_actions.update_one({"_id": operation}, {"$setOnInsert": {
        "onboarding_id": onboarding_id, "target": target, "state": "pending",
        "intent": expected, "created_at": now(),
    }}, upsert=True)
    database[target].update_one({"_id": record["_id"]}, {"$setOnInsert": {
        **expected, "operation_id": operation, "created_at": now(),
    }}, upsert=True)
    observed = database[target].find_one({"_id": record["_id"]})
    if observed is None or observed.get("operation_id") != operation or any(
        observed.get(field) != value for field, value in expected.items()
    ):
        database.workflow_actions.update_one({"_id": operation}, {"$set": {"state": "conflict"}})
        raise HTTPException(409, "The sandbox record conflicts with the requested action.")
    database.workflow_actions.update_one({"_id": operation}, {"$set": {
        "state": "verified", "reference": onboarding_id,
        "evidence": "Read back the sandbox record and matched the operation and expected fields.",
        "verified_at": now(),
    }})


def perform_stage_action(database, record):
    stage = record["stage"]
    if stage == 1:
        sandbox_effect(database, record, "verify", "sandbox_verifications", {
            "business_name": record["application"]["businessName"], "status": "reviewer_confirmed",
        })
    if stage == 5:
        sandbox_effect(database, record, "prepare-agreement", "sandbox_documents", {
            "content": (
                f"Sandbox business banking agreement\n\n"
                f"Business: {record['application']['businessName']}\n"
                f"Products: {record['application']['products']}\n\n"
                "This agreement is for demonstration only and carries no legal effect."
            ),
        })
    if stage == 8:
        signature = database.sandbox_signatures.find_one({"_id": record["_id"]})
        if signature is None:
            raise HTTPException(409, "A sandbox signature is required before provisioning.")
        sandbox_effect(database, record, "provision", "sandbox_accounts", {
            "reference": f"DEMO-{str(record['_id']).upper()}",
            "status": "active", "signer": signature["signer"],
        })


@router.post("/admin/onboardings/{onboarding_id}/review")
def review(onboarding_id: str, payload: Review, database: Db, actor: Admin):
    record = case(database, onboarding_id)
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
        rule = risk_policy(database, actor)
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
            if not database.sandbox_documents.find_one({"_id": record["_id"]}):
                raise HTTPException(409, "Prepare the agreement before releasing it.")
            updates["documents_released"] = True

    def persist(session):
        # Serialize a transition with its sandbox dispatch on the case revision.
        updated = change(database, session, record, updates, actor, "admin", payload.decision, comments)
        if payload.risk and record.get("risk"):
            if not comments:
                raise HTTPException(422, "Explain why the recorded risk assessment is changing.")
            override = ObjectId()
            database.overrides.insert_one({
                "_id": override, "onboarding_id": record["_id"], "before": record["risk"], "after": risk,
                "reason": comments, "actor_id": actor, "created_at": now(),
            }, session=session)
        return updated

    if payload.decision == "continue" and starting_status != "PAUSED" and stage in {1, 5, 8}:
        def persist_with_effect(session):
            updated = persist(session)
            # Target and intent write independently so the next attempt can reconcile them.
            perform_stage_action(database, record)
            return updated

        return admin_progress(transact(database, persist_with_effect))
    return admin_progress(transact(database, persist))


@router.get("/admin/workflow/runs/{onboarding_id}")
def workflow_run(onboarding_id: str, database: Db, actor: Admin):
    record = case(database, onboarding_id)
    return {
        "status": case_status(record), "currentNode": STEPS[record["stage"]],
        "checkpoint": record["revision"], "actions": action_trace(database, record),
    }


@router.post("/admin/workflow/runs/{onboarding_id}/retry")
def retry_workflow(onboarding_id: str, database: Db, actor: Admin):
    record = case(database, onboarding_id)
    if case_status(record) not in {"VERIFYING", "DOCUMENT_GENERATION", "PROVISIONING"}:
        raise HTTPException(409, "There is no sandbox action to retry at this step.")
    return review(onboarding_id, Review(
        revision=record["revision"], decision="continue", comments="Reconcile and retry sandbox action.",
    ), database, actor)


class Proposal(BaseModel):
    rule: Text
    onboardingId: str
    reason: Text


@router.get("/admin/guardrails")
def guardrails(database: Db, actor: Admin):
    active = database.guardrails.find_one({"_id": RISK_POLICY["key"]})
    if not active:
        return [{
            "key": RISK_POLICY["key"], "activeVersion": 1,
            "versions": [{"version": 1, "rule": "High risk requires a documented reviewer decision."}],
        }]
    return [{"key": active["_id"], "activeVersion": active["active_version"], "versions": active["versions"]}]


@router.get("/admin/guardrail-proposals")
def proposals(database: Db, actor: Admin):
    return [
        {**row, "id": str(row.pop("_id"))}
        for row in database.guardrail_proposals.find({}, {"actor_id": 0}).sort("created_at", -1)
    ]


@router.post("/admin/guardrail-proposals", status_code=201)
def propose(payload: Proposal, database: Db, actor: Admin):
    record = case(database, payload.onboardingId)
    override = database.overrides.find_one({"onboarding_id": record["_id"]}, sort=[("created_at", -1)])
    if not override:
        raise HTTPException(422, "Record a risk override on this onboarding before proposing a guardrail.")
    result = database.guardrail_proposals.insert_one({
        "rule": payload.rule, "reason": payload.reason, "status": "pending",
        "override": {"id": str(override["_id"]), "reason": override["reason"], "caseId": payload.onboardingId},
        "actor_id": actor, "created_at": now(),
    })
    return {"id": str(result.inserted_id)}


@router.post("/admin/guardrail-proposals/{proposal_id}/decision")
def decide_proposal(proposal_id: str, payload: ProposalDecision, database: Db, actor: Admin):
    key = object_id(proposal_id)

    def decide(session):
        proposal = database.guardrail_proposals.find_one_and_update(
            {"_id": key, "status": "pending"},
            {"$set": {
                "status": "approved" if payload.decision == "approve" else "rejected",
                "decisionReason": payload.comments, "decidedBy": str(actor), "decidedAt": now(),
            }},
            return_document=ReturnDocument.AFTER, session=session,
        )
        if proposal is None:
            raise HTTPException(409, "This proposal is no longer pending.")
        if payload.decision == "approve":
            baseline = {"version": 1, "rule": "High risk requires a documented reviewer decision."}
            policy_id = RISK_POLICY["key"]
            current = database.guardrails.find_one({"_id": policy_id}, session=session)
            version = current["active_version"] + 1 if current else 2
            versions = current["versions"] if current else [baseline]
            database.guardrails.update_one({"_id": policy_id}, {"$set": {
                "active_version": version,
                "versions": [*versions, {
                    "version": version, "rule": proposal["rule"], "proposalId": proposal_id,
                    "approvedBy": str(actor), "approvedAt": now(),
                }],
            }}, upsert=True, session=session)
        return {"status": proposal["status"]}

    return transact(database, decide)
