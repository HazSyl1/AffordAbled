from __future__ import annotations

import asyncio
import logging
import subprocess

from app.domain.exceptions import InvalidSpeechInputError

logger = logging.getLogger(__name__)


class FFmpegAudioTranscoder:
    def __init__(self, *, binary: str = 'ffmpeg', timeout_seconds: int = 15) -> None:
        self._binary = binary
        self._timeout_seconds = timeout_seconds

    async def to_wav(self, audio_bytes: bytes, *, source_content_type: str) -> bytes:
        command = [
            self._binary,
            '-hide_banner',
            '-loglevel',
            'error',
            '-i',
            'pipe:0',
            '-ac',
            '1',
            '-ar',
            '16000',
            '-f',
            'wav',
            'pipe:1',
        ]

        try:
            completed_process = await asyncio.to_thread(
                subprocess.run,
                command,
                input=audio_bytes,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise InvalidSpeechInputError(
                'Audio conversion service is unavailable. Install ffmpeg on the API server or upload WAV.'
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise InvalidSpeechInputError(
                'Audio conversion timed out. Upload a shorter clip (up to 15 seconds) or use WAV.'
            ) from exc

        stdout = completed_process.stdout
        stderr = completed_process.stderr

        if completed_process.returncode != 0 or not stdout:
            error_details = stderr.decode('utf-8', errors='ignore').strip()
            logger.warning(
                'speech.transcoding.failed',
                extra={
                    'source_content_type': source_content_type,
                    'return_code': completed_process.returncode,
                    'error': error_details[:400],
                },
            )
            raise InvalidSpeechInputError(
                'Could not convert uploaded audio to WAV. Please retry with a clearer clip or upload WAV.'
            )

        return stdout
