import unittest
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.routers import Review, checked_signature, signed_workflow_review
from app.workflow import SIGNED_WORKFLOW, progress
from app.workflow_agents import EvidenceCheck, cited_sources


class SignedWorkflowTest(unittest.IsolatedAsyncioTestCase):
    async def test_signature_must_match_released_content(self):
        digest = sha256(b"original agreement").hexdigest()
        database = SimpleNamespace(sandbox_documents=SimpleNamespace(find_one=AsyncMock(return_value={
            "content": "edited agreement", "digest": digest, "template_version": 1,
        })))
        with self.assertRaises(HTTPException) as caught:
            await checked_signature(database, {"_id": ObjectId(), "released_digest": digest})
        self.assertEqual(caught.exception.status_code, 409)

    async def test_material_gaps_block_final_approval(self):
        record = {
            "_id": ObjectId(), "workflow": SIGNED_WORKFLOW, "stage": 5,
            "status": "ADMIN_REVIEW", "risk": {"missingInputs": ["Ownership record"]},
        }
        with self.assertRaises(HTTPException) as caught:
            await signed_workflow_review(None, record, Review(revision=1, decision="continue", comments="Approved."), ObjectId())
        self.assertEqual(caught.exception.status_code, 422)

    async def test_only_bank_approval_provisions_completed_case(self):
        record = {
            "_id": ObjectId(), "workflow": SIGNED_WORKFLOW, "stage": 5,
            "status": "ADMIN_REVIEW", "risk": {"tier": "high", "missingInputs": []},
            "verification": {"agreementDigest": "digest"},
        }
        with (
            patch("app.routers.checked_signature", new=AsyncMock(return_value={"digest": "digest", "signer": "Demo"})),
            patch("app.routers.sandbox_effect", new=AsyncMock()) as effect,
            patch("app.routers.change", new=AsyncMock(return_value={**record, "stage": 6, "status": "ONBOARDED"})) as change,
        ):
            result = await signed_workflow_review(None, record, Review(revision=1, decision="continue", comments="Reviewed."), ObjectId())
        self.assertEqual(result["status"], "ONBOARDED")
        self.assertNotIn("risk", progress(record))
        self.assertNotIn("verification", progress(record))
        self.assertEqual(effect.await_args.args[2], "provision")
        self.assertEqual(change.await_args.args[5], "approve")

    def test_unknown_citations_are_rejected(self):
        result = EvidenceCheck(findings=["Ownership reviewed"], sourceIds=["unknown"], missingInputs=[])
        with self.assertRaises(ValueError):
            cited_sources(result, [{"_id": "known", "citation": "Section 138"}])
