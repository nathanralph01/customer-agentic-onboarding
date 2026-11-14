"""Model-independent onboarding transitions and sandbox handoffs."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

STEPS = (
    "Apply", "Verify", "Risk", "Compliance", "Risk Review", "Documents",
    "Document Review", "Sign", "Provision", "Onboard",
)
STATES = (
    "APPLIED", "VERIFYING", "RISK_ASSESSMENT", "COMPLIANCE_CHECK",
    "ADMIN_REVIEW", "DOCUMENT_GENERATION", "ADMIN_REVIEW",
    "AWAITING_SIGNATURE", "PROVISIONING", "ONBOARDED",
)
TERMINAL = {"ONBOARDED", "CANCELLED"}
GATES = {4, 6}
DURATIONS = (0, 10, 15, 15, 20, 10, 20, 10, 5, 0)
REQUIRED_DOCUMENTS = (
    "Business registration record",
    "Ownership record",
)
RISK_POLICY = {
    "key": "sandbox-intake-risk",
    "version": 1,
    "categories": ["Ownership", "Business activity", "Geography"],
    "scale": "1 (lowest) to 5 (highest)",
}


SIGNED_WORKFLOW = "signed-agreement-v1"
SIGNED_STEPS = ("Apply", "Prepare agreement", "Document Review", "Sign and return", "Verify evidence", "Final bank review", "Onboard")
SIGNED_STATES = ("APPLIED", "DOCUMENT_GENERATION", "ADMIN_REVIEW", "AWAITING_SIGNATURE", "VERIFYING", "ADMIN_REVIEW", "ONBOARDED")


def uses_signed_workflow(record):
    return record.get("workflow") == SIGNED_WORKFLOW


def workflow_steps(record):
    return SIGNED_STEPS if uses_signed_workflow(record) else STEPS


def now():
    return datetime.now(timezone.utc)


def progress(record):
    index = record.get("stage", 0)
    status = case_status(record)
    team = "Customer Onboarding" if index in {0, 7, 9} else "Business Banking Operations"
    steps = workflow_steps(record)
    minutes = sum((0, 10, 20, 10, 15, 20, 0)[index:]) if uses_signed_workflow(record) else sum(DURATIONS[index:])
    waiting = status in {"NEEDS_INFO", "PAUSED", "ADMIN_REVIEW", "AWAITING_SIGNATURE"}
    complete = len(steps) if status == "ONBOARDED" else index
    return {
        "id": str(record["_id"]),
        "conversationId": record.get("client_id"),
        "status": status,
        "stage": index,
        "currentStep": steps[index],
        "steps": list(steps),
        "completed": complete,
        "revision": record.get("revision", 0),
        "signedWorkflow": uses_signed_workflow(record),
        "agreementSigned": bool(record.get("agreement_signed")),
        "rejected": bool(record.get("rejected")),
        "submittedAt": record.get("submitted_at"),
        "application": record.get("application", {}),
        "requiredDocuments": record.get("required_documents", []),
        "requestedInformation": record.get("requested_information", "") if status == "NEEDS_INFO" else "",
        "informationResponses": record.get("information_responses", []),
        "estimatedMinutes": minutes if status not in TERMINAL else None,
        "estimatedCompletion": record["updated_at"] + timedelta(minutes=minutes) if not waiting and status not in TERMINAL else None,
        "contact": {
            "name": team,
            "email": "onboarding@customer360.example",
            "phone": "+1-202-555-0148",
        },
    }


def transition(row, decision, comments):
    status = case_status(row)
    stage = row["stage"]
    if status in TERMINAL or status == "DRAFT":
        raise HTTPException(409, "This onboarding cannot be changed.")
    if decision == "cancel":
        return {"status": "CANCELLED"}
    if decision == "pause" and status not in {"PAUSED", "NEEDS_INFO"}:
        return {"status": "PAUSED", "resume_status": status}
    if decision == "request_info" and status not in {"PAUSED", "NEEDS_INFO"}:
        if not comments:
            raise HTTPException(422, "Describe the information you need.")
        return {
            "status": "NEEDS_INFO",
            "resume_status": status,
            "requested_information": comments,
        }
    if decision == "continue":
        if status == "PAUSED":
            return {"status": row["resume_status"]}
        if status not in {"NEEDS_INFO", "AWAITING_SIGNATURE"} and stage < len(STEPS) - 1:
            return {"status": STATES[stage + 1], "stage": stage + 1}
    raise HTTPException(409, "This action is unavailable at the current step.")


def case_status(record):
    # Older Atlas validators omit PROVISIONING. Stage eight represents that state.
    if not uses_signed_workflow(record) and record.get("stage") == 8 and record["status"] == "AWAITING_SIGNATURE":
        return "PROVISIONING"
    return record["status"]
