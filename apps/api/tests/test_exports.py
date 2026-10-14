from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import ExportArtifactModel, UserModel
from tests.helpers import auth_headers, register_and_get_token


async def test_get_export_download_url_returns_link_for_owner(client: AsyncClient, db_session: AsyncSession) -> None:
    email = 'exports-owner@example.com'
    token = await register_and_get_token(client, email)
    owner_user_id = await _get_user_id_by_email(db_session, email)

    export_id = uuid.uuid4()
    db_session.add(
        ExportArtifactModel(
            id=export_id,
            user_id=owner_user_id,
            format='pdf',
            download_url='https://example.com/reports/export-1.pdf',
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.get(f'/api/v1/exports/{export_id}/download-url', headers=auth_headers(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload['export_id'] == str(export_id)
    assert payload['download_url'] == 'https://example.com/reports/export-1.pdf'


async def test_get_export_download_url_rejects_other_users_export(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_email = 'exports-owner-2@example.com'
    owner_token = await register_and_get_token(client, owner_email)
    owner_user_id = await _get_user_id_by_email(db_session, owner_email)

    other_token = await register_and_get_token(client, 'exports-other@example.com')

    export_id = uuid.uuid4()
    db_session.add(
        ExportArtifactModel(
            id=export_id,
            user_id=owner_user_id,
            format='xlsx',
            download_url='https://example.com/reports/export-2.xlsx',
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    response = await client.get(f'/api/v1/exports/{export_id}/download-url', headers=auth_headers(other_token))
    assert response.status_code == 404

    # Sanity check owner can still fetch it
    owner_response = await client.get(f'/api/v1/exports/{export_id}/download-url', headers=auth_headers(owner_token))
    assert owner_response.status_code == 200


async def test_get_export_download_url_rejects_expired_link(client: AsyncClient, db_session: AsyncSession) -> None:
    email = 'exports-expired@example.com'
    token = await register_and_get_token(client, email)
    user_id = await _get_user_id_by_email(db_session, email)

    export_id = uuid.uuid4()
    db_session.add(
        ExportArtifactModel(
            id=export_id,
            user_id=user_id,
            format='pdf',
            download_url='https://example.com/reports/export-expired.pdf',
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    await db_session.commit()

    response = await client.get(f'/api/v1/exports/{export_id}/download-url', headers=auth_headers(token))
    assert response.status_code == 410


async def _get_user_id_by_email(db_session: AsyncSession, email: str) -> uuid.UUID:
    result = await db_session.execute(select(UserModel).where(UserModel.email == email))
    user = result.scalar_one()
    return user.id
