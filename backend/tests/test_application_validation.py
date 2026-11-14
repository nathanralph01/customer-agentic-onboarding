import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routers import validate_application
from app.workflow_agents import ApplicationValidation


class ApplicationValidationTest(unittest.IsolatedAsyncioTestCase):
    application = {
        "businessName": "Cedar Finch", "businessActivity": "Retail of office supplies",
        "registration": "Ontario, Canada", "owners": "Jordan Vale 100%",
        "products": "Business account", "sector": "Retail",
    }

    async def test_placeholder_is_rejected_without_calling_model(self):
        with patch("app.routers.agent_result", new_callable=AsyncMock) as agent:
            with self.assertRaises(HTTPException) as error:
                await validate_application({**self.application, "businessName": "I don’t know."})
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(error.exception.detail["fields"][0]["field"], "businessName")
        agent.assert_not_awaited()

    async def test_model_issues_reach_the_form(self):
        result = ApplicationValidation(issues=[{"field": "owners", "message": "Include ownership percentages."}])
        application = {**self.application, "owners": "Jordan Vale"}
        with (
            patch.dict("os.environ", {"ONBOARDING_CHAT_MODEL": "test:model"}),
            patch("app.routers.agent_result", new=AsyncMock(return_value=(result, []))) as agent,
            self.assertRaises(HTTPException) as error,
        ):
            await validate_application(application)
        agent.assert_awaited_once_with("application-validation", ApplicationValidation, {"application": application})
        self.assertEqual(error.exception.detail["fields"], [{"field": "owners", "message": "Include ownership percentages."}])

    async def test_valid_model_result_allows_submission(self):
        with (
            patch.dict("os.environ", {"ONBOARDING_CHAT_MODEL": "test:model"}),
            patch("app.routers.agent_result", new=AsyncMock(return_value=(ApplicationValidation(issues=[]), []))),
        ):
            await validate_application(self.application)
