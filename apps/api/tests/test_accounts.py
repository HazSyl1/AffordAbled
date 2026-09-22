from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_auth_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, "auth-smoke@example.com")

    me_response = await client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "auth-smoke@example.com"


async def test_accounts_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, "accounts-smoke@example.com")

    create_response = await client.post(
        "/api/v1/accounts",
        json={"name": "Everyday Wallet", "type": "wallet", "balance_paise": 10000, "currency": "INR"},
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201
    account_id = create_response.json()["id"]

    list_response = await client.get("/api/v1/accounts", headers=auth_headers(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = await client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers(token))
    assert get_response.status_code == 200
    assert get_response.json()["balance_paise"] == 10000
