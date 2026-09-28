from __future__ import annotations

from dataclasses import dataclass

from app.domain.exceptions import ImageAnalysisError, InvalidImageInputError
from app.domain.ports import ImageToTextClient

_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_SUPPORTED_IMAGE_CONTENT_TYPES = {
    'image/jpeg',
    'image/jpg',
    'image/png',
    'image/webp',
}
_MAX_EXTRACTED_TEXT_CHARS = 1800


@dataclass
class ImageAnalysisOutput:
    extracted_text: str
    prompt: str


@dataclass
class ImageService:
    image_to_text_client: ImageToTextClient

    async def analyze_image(
        self,
        image_bytes: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ImageAnalysisOutput:
        if not image_bytes:
            raise InvalidImageInputError('Image file is empty')

        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise InvalidImageInputError('Image file exceeds 10MB limit')

        if not content_type.startswith('image/'):
            raise InvalidImageInputError('Only image uploads are supported')

        normalized_content_type = content_type.split(';', maxsplit=1)[0].strip().lower()
        if normalized_content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise InvalidImageInputError('Unsupported image format. Use JPG, PNG, or WEBP.')

        extracted_text = (
            await self.image_to_text_client.analyze(image_bytes, content_type=normalized_content_type)
        ).strip()
        if not extracted_text:
            raise ImageAnalysisError('Image analysis returned empty text')

        compact_text = ' '.join(extracted_text.split())[:_MAX_EXTRACTED_TEXT_CHARS]
        safe_filename = (filename or 'uploaded image').strip() or 'uploaded image'
        prompt = (
            f'I uploaded a receipt/bill image ({safe_filename}). '
            f'Extracted text: {compact_text}. '
            'Help me log the transaction from this and ask for missing fields if needed.'
        )

        return ImageAnalysisOutput(extracted_text=compact_text, prompt=prompt)
