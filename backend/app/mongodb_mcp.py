"""Atlas Managed MCP client. Run: python -m app.mongodb_mcp [--check-database]."""

import argparse
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[2]
MCP_URL = "https://mcp.mongodb.com"
TOKEN_URL = "https://cloud.mongodb.com/api/oauth/token"


def credentials() -> tuple[str, str]:
    load_dotenv(ROOT / "database/.env")
    client_id = os.getenv("MDB_MCP_API_CLIENT_ID", "").strip()
    secret = os.getenv("MDB_MCP_API_CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        raise ValueError("Set MDB_MCP_API_CLIENT_ID and MDB_MCP_API_CLIENT_SECRET in the environment or database/.env.")
    # Match the portal's variable, but refuse to send bearer tokens elsewhere.
    if os.getenv("MDB_MCP_API_BASE_URL", MCP_URL).rstrip("/") != MCP_URL:
        raise ValueError("MDB_MCP_API_BASE_URL must be https://mcp.mongodb.com.")
    return client_id, secret


class AtlasAuth(httpx.Auth):
    """Acquire and refresh short-lived OAuth tokens without persisting them."""

    def __init__(self, client_id: str, secret: str):
        self._client_id = client_id
        self._secret = secret
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def async_auth_flow(self, request):
        # Never attach credentials to another origin, including redirects.
        if request.url.scheme != "https" or request.url.host != "mcp.mongodb.com" or request.url.port not in (None, 443):
            raise ValueError("Atlas MCP authentication is restricted to https://mcp.mongodb.com.")
        async with self._lock:
            if time.monotonic() >= self._expires_at:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    response = await client.post(
                        TOKEN_URL,
                        auth=httpx.BasicAuth(self._client_id, self._secret),
                        data={"grant_type": "client_credentials"},
                        headers={"Accept": "application/json"},
                    )
                if response.status_code != 200:
                    raise RuntimeError(f"Atlas OAuth authentication failed (HTTP {response.status_code}). Check the rotated MCP credentials and API access list.")
                try:
                    payload = response.json()
                    token = payload["access_token"]
                    lifetime = float(payload.get("expires_in", 3600))
                    if not isinstance(token, str) or not token or lifetime <= 0:
                        raise ValueError()
                except (KeyError, TypeError, ValueError):
                    raise RuntimeError("Atlas OAuth returned an invalid token response.") from None
                self._token = token
                self._expires_at = time.monotonic() + max(0, lifetime - 60)
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


@asynccontextmanager
async def mongodb_mcp_session() -> AsyncIterator[ClientSession]:
    """Connect directly to MongoDB's hosted server; keep open for an agent run.

    Configure read-only access on the Atlas Managed MCP configuration itself.
    Enter and exit this context within the same async task.
    """
    client_id, secret = credentials()
    async with httpx.AsyncClient(
        auth=AtlasAuth(client_id, secret),
        headers={"Accept": "application/json, text/event-stream"},
        timeout=httpx.Timeout(60, read=300),
        follow_redirects=False,
    ) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session:
                await session.initialize()
                yield session


async def check(check_database: bool = False) -> None:
    async with mongodb_mcp_session() as session:
        result = await session.list_tools()
        names = [tool.name for tool in result.tools]
        while result.nextCursor:
            result = await session.list_tools(cursor=result.nextCursor)
            names.extend(tool.name for tool in result.tools)
        print(f"Atlas Managed MCP connected; {len(names)} tools available:")
        print("\n".join(sorted(names)))
        if check_database:
            project = os.getenv("MDB_MCP_PROJECT_ID")
            cluster = os.getenv("MDB_MCP_CLUSTER_NAME")
            database = os.getenv("MONGODB_DATABASE")
            if not project or not cluster or not database:
                raise ValueError("Database check requires MDB_MCP_PROJECT_ID, MDB_MCP_CLUSTER_NAME and MONGODB_DATABASE.")
            connected = await session.call_tool("remote-atlas-connect", {"projectId": project, "clusterName": cluster})
            content = connected.structuredContent or {}
            connection_id = content.get("connectionId")
            if connected.isError or not connection_id:
                raise RuntimeError("Atlas MCP cluster connection failed or returned no connectionId. Check configuration roles and cluster access.")
            result = await session.call_tool("list-collections", {"connectionId": connection_id, "database": database})
            if result.isError:
                raise RuntimeError("Atlas MCP database read failed. Check configuration roles and cluster access.")
            print("Atlas database read succeeded (list-collections).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-database", action="store_true", help="Connect to the configured Atlas cluster and list collections")
    args = parser.parse_args()
    asyncio.run(check(args.check_database))


if __name__ == "__main__":
    main()
