from __future__ import annotations

from httpx import AsyncClient

REGISTER_URL = '/api/v1/auth/register'


async def register_and_get_token(client: AsyncClient, email: str, password: str = 'SuperSecret123') -> str:
    fallback_name = email.split('@')[0].replace('.', ' ').replace('-', ' ').strip().title() or 'Test User'
    response = await client.post(
        REGISTER_URL,
        json={
            'email': email,
            'name': fallback_name,
            'date_of_birth': '1998-01-01',
            'password': password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()['access_token']


def auth_headers(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}
