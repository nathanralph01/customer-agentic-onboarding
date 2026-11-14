import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app import mongodb_mcp as mcp


class MongoDBMCPTest(unittest.IsolatedAsyncioTestCase):
    def test_missing_credentials(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(mcp, "load_dotenv"):
            with self.assertRaisesRegex(ValueError, "MDB_MCP_API_CLIENT_ID"):
                mcp.credentials()

    def test_rejects_another_endpoint(self):
        with patch.dict("os.environ", {
            "MDB_MCP_API_CLIENT_ID": "test-id", "MDB_MCP_API_CLIENT_SECRET": "test-secret",
            "MDB_MCP_API_BASE_URL": "https://example.com",
        }, clear=True), patch.object(mcp, "load_dotenv"):
            with self.assertRaisesRegex(ValueError, "mcp.mongodb.com"):
                mcp.credentials()

    async def test_oauth_token_is_cached_and_refreshed(self):
        responses = [
            httpx.Response(200, json={"access_token": "first", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "second", "expires_in": 3600}),
        ]
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.side_effect = responses
        auth = mcp.AtlasAuth("test-id", "test-secret")
        with patch.object(mcp.httpx, "AsyncClient", return_value=client):
            for expected in ("first", "first", "second"):
                if expected == "second":
                    auth._expires_at = 0
                request = httpx.Request("POST", mcp.MCP_URL)
                flow = auth.async_auth_flow(request)
                outgoing = await anext(flow)
                self.assertEqual(outgoing.headers["Authorization"], f"Bearer {expected}")
                await flow.aclose()
        self.assertEqual(client.post.await_count, 2)
        self.assertEqual(client.post.call_args.args[0], mcp.TOKEN_URL)
        self.assertEqual(client.post.call_args.kwargs["data"], {"grant_type": "client_credentials"})

    async def test_auth_failure_does_not_expose_response_or_secret(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(401, text="sensitive response")
        with patch.object(mcp.httpx, "AsyncClient", return_value=client):
            flow = mcp.AtlasAuth("test-id", "test-secret").async_auth_flow(httpx.Request("POST", mcp.MCP_URL))
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
                await anext(flow)
        self.assertNotIn("sensitive response", str(error.exception))
        self.assertNotIn("test-secret", str(error.exception))

    async def test_auth_refuses_another_origin(self):
        flow = mcp.AtlasAuth("test-id", "test-secret").async_auth_flow(httpx.Request("POST", "https://example.com"))
        with self.assertRaises(ValueError):
            await anext(flow)

    async def test_session_initializes_and_cleans_up_on_error(self):
        closed = []

        @asynccontextmanager
        async def transport(url, **kwargs):
            self.assertEqual(url, mcp.MCP_URL)
            try:
                yield "read", "write", None
            finally:
                closed.append(True)

        session = AsyncMock()
        session.__aenter__.return_value = session
        client = AsyncMock()
        client.__aenter__.return_value = client
        with (
            patch.object(mcp, "credentials", return_value=("test-id", "test-secret")),
            patch.object(mcp.httpx, "AsyncClient", return_value=client),
            patch.object(mcp, "streamable_http_client", transport),
            patch.object(mcp, "ClientSession", return_value=session),
        ):
            with self.assertRaisesRegex(RuntimeError, "consumer"):
                async with mcp.mongodb_mcp_session():
                    session.initialize.assert_awaited_once()
                    raise RuntimeError("consumer")
        session.__aexit__.assert_awaited_once()
        client.__aexit__.assert_awaited_once()
        self.assertEqual(closed, [True])

    async def test_database_check_uses_managed_connection_id(self):
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[], nextCursor=None)
        session.call_tool.side_effect = [
            SimpleNamespace(isError=False, structuredContent={"connectionId": "managed-id"}),
            SimpleNamespace(isError=False),
        ]

        @asynccontextmanager
        async def connection():
            yield session

        with (
            patch.dict("os.environ", {"MDB_MCP_PROJECT_ID": "project", "MDB_MCP_CLUSTER_NAME": "cluster", "MONGODB_DATABASE": "onboarding"}),
            patch.object(mcp, "mongodb_mcp_session", connection), patch("builtins.print"),
        ):
            await mcp.check(True)
        self.assertEqual(session.call_tool.call_args_list[0].args, ("remote-atlas-connect", {"projectId": "project", "clusterName": "cluster"}))
        session.call_tool.assert_awaited_with("list-collections", {"connectionId": "managed-id", "database": "onboarding"})
