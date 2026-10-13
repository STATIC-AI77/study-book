"""
Kaggle Podcast Runner.

Orchestrates long-form monologue and multi-speaker podcast generation on Kaggle:
Submits script generation to the TPU cluster, parallel TTS audio synthesis
to the 96 vCPU host, and downloads/saves the final stitched MP3 file and transcript.
"""

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional
import httpx
from loguru import logger

from backend.ai.kaggle.client import KaggleClient


class KagglePodcastRunner:
    """Coordinates podcast generation requests with the Kaggle TPU/Host backend."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.client = KaggleClient(base_url=base_url, api_key=api_key, timeout=240.0)

    async def generate_podcast(
        self,
        content: str,
        briefing: str,
        episode_name: str,
        output_dir: Path,
        duration_minutes: int = 15,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Request complete podcast generation from Kaggle TPU backend.
        Saves outline.json, transcript.json, and audio.mp3 to output_dir.
        """
        logger.info(
            f"Submitting podcast request to Kaggle TPU backend (duration: ~{duration_minutes}m, language: {language})"
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        resp = await self.client.generate_podcast(
            content=content,
            briefing=briefing,
            episode_name=episode_name,
            duration_minutes=duration_minutes,
            language=language,
        )

        outline = resp.get("outline", {})
        transcript = resp.get("transcript", [])
        audio_file_path = output_dir / "audio.mp3"

        # 1. Unpack Audio
        audio_base64 = resp.get("audio_base64")
        audio_url = resp.get("audio_url")

        if audio_base64:
            audio_bytes = base64.b64decode(audio_base64)
            audio_file_path.write_bytes(audio_bytes)
            logger.info(f"Saved Kaggle-generated audio ({len(audio_bytes)} bytes) to {audio_file_path}")
        elif audio_url:
            logger.info(f"Downloading generated audio from Kaggle: {audio_url}")
            async with httpx.AsyncClient(timeout=60.0) as dl_client:
                dl_resp = await dl_client.get(audio_url, headers=self.client._get_headers())
                if dl_resp.status_code == 200:
                    audio_file_path.write_bytes(dl_resp.content)
                else:
                    raise RuntimeError(f"Failed to download audio from Kaggle: HTTP {dl_resp.status_code}")
        else:
            raise RuntimeError("Kaggle podcast response contained neither 'audio_base64' nor 'audio_url'")

        # 2. Persist outline & transcript in episode folder
        if outline:
            (output_dir / "outline.json").write_text(json.dumps(outline, indent=2))
        if transcript:
            (output_dir / "transcript.json").write_text(json.dumps(transcript, indent=2))

        return {
            "outline": outline,
            "transcript": transcript,
            "final_output_file_path": str(audio_file_path),
            "output_dir": output_dir,
        }
