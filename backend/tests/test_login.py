import unittest

from httpx import ASGITransport, AsyncClient

from app.main import app


class LoginTest(unittest.IsolatedAsyncioTestCase):
    async def test_login_returns_json_true_without_credentials(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/login")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json(), True)


if __name__ == "__main__":
    unittest.main()
