from __future__ import annotations

import httpx

from app.core.config import Settings
from app.domain.ports import GoogleProfile

GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'


class GoogleAuthClient:
    def __init__(self, settings: Settings) -> None:
        self._client_id = settings.google_client_id
        self._client_secret = settings.google_client_secret

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleProfile:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    'code': code,
                    'client_id': self._client_id,
                    'client_secret': self._client_secret,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                },
            )
            token_response.raise_for_status()
            access_token = token_response.json()['access_token']

            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={'Authorization': f'Bearer {access_token}'},
            )
            userinfo_response.raise_for_status()
            data = userinfo_response.json()

        return GoogleProfile(
            sub=data['sub'],
            email=data['email'],
            name=data.get('name'),
        )
