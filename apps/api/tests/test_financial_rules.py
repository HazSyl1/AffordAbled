from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_get_token


async def test_balance_paise_must_be_non_negative(client: AsyncClient) -> None:
    token = await register_and_get_token(client, "paise-rule@example.com")

    response = await client.post(
        "/api/v1/accounts",
        json={"name": "Invalid Account", "type": "cash", "balance_paise": -500, "currency": "INR"},
        headers=auth_headers(token),
    )

    assert response.status_code == 422


async def test_user_cannot_access_another_users_account(client: AsyncClient) -> None:
    owner_token = await register_and_get_token(client, "owner@example.com")
    other_token = await register_and_get_token(client, "other-user@example.com")

    create_response = await client.post(
        "/api/v1/accounts",
        json={"name": "Owner's Savings", "type": "bank", "balance_paise": 500000, "currency": "INR"},
        headers=auth_headers(owner_token),
    )
    account_id = create_response.json()["id"]

    # A different authenticated user must not be able to read this account,
    # and the response must not reveal whether the ID exists at all.
    response = await client.get(f"/api/v1/accounts/{account_id}", headers=auth_headers(other_token))
    assert response.status_code == 404

    other_list_response = await client.get("/api/v1/accounts", headers=auth_headers(other_token))
    assert other_list_response.json() == []
