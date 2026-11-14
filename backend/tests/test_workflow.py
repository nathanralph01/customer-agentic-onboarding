import unittest

from fastapi import HTTPException

from app.workflow import transition


class WorkflowTest(unittest.TestCase):
    def test_two_review_gates(self):
        first = transition({"status": "COMPLIANCE_CHECK", "stage": 3}, "continue", "")
        second = transition({"status": "DOCUMENT_GENERATION", "stage": 5}, "continue", "")
        self.assertEqual(first, {"status": "ADMIN_REVIEW", "stage": 4})
        self.assertEqual(second, {"status": "ADMIN_REVIEW", "stage": 6})
        self.assertEqual(transition(second, "continue", "")["status"], "AWAITING_SIGNATURE")

    def test_pause_retains_review_stage(self):
        review = {"status": "ADMIN_REVIEW", "stage": 6}
        paused = {**review, **transition(review, "pause", "")}
        self.assertEqual(transition(paused, "continue", ""), {"status": "ADMIN_REVIEW"})

    def test_information_request_requires_instructions(self):
        with self.assertRaises(HTTPException) as error:
            transition({"status": "ADMIN_REVIEW", "stage": 4}, "request_info", "")
        self.assertEqual(error.exception.status_code, 422)

    def test_signature_cannot_be_bypassed(self):
        with self.assertRaises(HTTPException) as error:
            transition({"status": "AWAITING_SIGNATURE", "stage": 7}, "continue", "")
        self.assertEqual(error.exception.status_code, 409)

    def test_terminal_cases_cannot_be_modified(self):
        for stage, status in [(9, "ONBOARDED"), (4, "CANCELLED")]:
            with self.subTest(status=status), self.assertRaises(HTTPException):
                transition({"status": status, "stage": stage}, "cancel", "")
