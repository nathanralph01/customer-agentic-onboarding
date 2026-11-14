import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


class LoginTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_uses_managed_mcp_without_a_database_uri(self):
        session = AsyncMock()
        session.call_tool.return_value = SimpleNamespace(isError=False, structuredContent={"connectionId": "managed"})

        @asynccontextmanager
        async def connection():
            yield session

        with (
            patch.dict("os.environ", {"MONGODB_DATABASE": "test", "MDB_MCP_PROJECT_ID": "project", "MDB_MCP_CLUSTER_NAME": "cluster"}, clear=True),
            patch("app.main.mongodb_mcp_session", connection),
        ):
            async with lifespan(app):
                self.assertEqual(app.state.database.connection_id, "managed")
                self.assertEqual(app.state.database.name, "test")
        self.assertIsNone(app.state.database)
        session.call_tool.assert_awaited_once_with("remote-atlas-connect", {"projectId": "project", "clusterName": "cluster"})

    async def test_login_returns_json_true_without_credentials(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/login")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json(), True)


if __name__ == "__main__":
    unittest.main()
