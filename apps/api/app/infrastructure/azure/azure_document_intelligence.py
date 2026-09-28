from __future__ import annotations

import asyncio

import httpx

from app.core.config import Settings
from app.domain.exceptions import ImageAnalysisError, ImageServiceNotConfiguredError, InvalidImageInputError

_ANALYZE_MODEL = 'prebuilt-layout'
_API_VERSION = '2024-11-30'
_POLL_MAX_ATTEMPTS = 12
_POLL_DELAY_SECONDS = 1.0


class AzureDocumentIntelligenceClient:
    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.azure_document_intelligence_endpoint.rstrip('/')
        self._api_key = settings.azure_document_intelligence_key

    async def analyze(self, image_bytes: bytes, *, content_type: str) -> str:
        if not self._endpoint or not self._api_key:
            raise ImageServiceNotConfiguredError('Azure Document Intelligence credentials are not configured')

        analyze_url = (
            f'{self._endpoint}/documentintelligence/documentModels/{_ANALYZE_MODEL}:analyze'
            f'?api-version={_API_VERSION}'
        )
        headers = {
            'Ocp-Apim-Subscription-Key': self._api_key,
            'Content-Type': content_type,
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(analyze_url, headers=headers, content=image_bytes)

                if response.status_code == 400:
                    raise InvalidImageInputError('Document Intelligence rejected the image input')
                if response.status_code != 202:
                    raise ImageAnalysisError('Document Intelligence request failed')

                operation_location = response.headers.get('Operation-Location')
                if not operation_location:
                    raise ImageAnalysisError('Document Intelligence did not return an operation location')

                poll_headers = {'Ocp-Apim-Subscription-Key': self._api_key}
                for _ in range(_POLL_MAX_ATTEMPTS):
                    poll_response = await client.get(operation_location, headers=poll_headers)
                    if poll_response.status_code != 200:
                        raise ImageAnalysisError('Document Intelligence polling failed')

                    poll_payload = poll_response.json()
                    status = str(poll_payload.get('status') or '').lower()
                    if status == 'succeeded':
                        content = str((poll_payload.get('analyzeResult') or {}).get('content') or '').strip()
                        if not content:
                            raise ImageAnalysisError('Document Intelligence returned empty extracted text')
                        return content
                    if status == 'failed':
                        raise ImageAnalysisError('Document Intelligence analysis failed')

                    await asyncio.sleep(_POLL_DELAY_SECONDS)
        except httpx.HTTPError as exc:
            raise ImageAnalysisError('Document Intelligence request failed') from exc

        raise ImageAnalysisError('Document Intelligence timed out before analysis completed')

