"""
Kaggle TPU backend client.

Provides an HTTP client tailored for interacting with a Kaggle notebook server
running on a TPU v3-8 / v4-8 instance with a host CPU. Includes tunnel bypass
headers (ngrok / Cloudflare), extended timeouts, and support for all AI modalities.
"""

import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import httpx
from loguru import logger


class KaggleClient:
    """Client for connecting to the Kaggle TPU backend server."""

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        clean_base = (base_url or "").strip().rstrip("/")
        for suffix in ["/api/podcast", "/v1/models", "/v1", "/api"]:
            if clean_base.endswith(suffix):
                clean_base = clean_base[:-len(suffix)].rstrip("/")
        self.base_url = clean_base
        self.api_key = (api_key or "").strip() if api_key else None
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "StudyBook-TPU-Client/1.0",
            # Bypass ngrok free tier browser warning interstitial
            "ngrok-skip-browser-warning": "1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["x-api-key"] = self.api_key
        return headers

    def _normalize_url(self, path: str) -> str:
        clean_path = path.lstrip("/")
        return f"{self.base_url}/{clean_path}"

    async def health_check(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check connectivity to the Kaggle backend.
        Probes /health, falling back to /ping and /v1/models.
        """
        if not self.base_url:
            return False, "Kaggle base URL is not configured", {}

        headers = self._get_headers()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # 1. Try GET /health
            try:
                resp = await client.get(self._normalize_url("health"), headers=headers)
                if resp.status_code == 200:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return True, "Kaggle backend is online and healthy (/health)", data
            except Exception as e:
                logger.debug(f"Kaggle /health check probe failed: {e}")

            # 2. Try GET /ping
            try:
                resp = await client.get(self._normalize_url("ping"), headers=headers)
                if resp.status_code == 200:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return True, "Kaggle backend is online (/ping responded)", data
            except Exception as e:
                logger.debug(f"Kaggle /ping check probe failed: {e}")

            # 3. Fallback to GET /v1/models
            try:
                resp = await client.get(self._normalize_url("v1/models"), headers=headers)
                if resp.status_code == 200:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return True, "Kaggle backend is reachable (/v1/models responded)", data
                return False, f"Kaggle backend returned HTTP {resp.status_code}", {}
            except Exception as e:
                logger.warning(f"Kaggle connection error: {e}")
                return False, f"Could not connect to Kaggle backend: {str(e)}", {}

    async def discover_models(self) -> List[Dict[str, Any]]:
        """
        Enumerate models served on the Kaggle backend.
        """
        if not self.base_url:
            return []

        headers = self._get_headers()
        models: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                # 1. Check /v1/models
                resp = await client.get(self._normalize_url("v1/models"), headers=headers)
                if resp.status_code == 200:
                    payload = resp.json()
                    data_items = payload.get("data") if isinstance(payload, dict) else payload
                    if isinstance(data_items, list):
                        for item in data_items:
                            m_id = item.get("id") or item.get("name")
                            if m_id:
                                m_type = item.get("type") or "language"
                                models.append({
                                    "name": m_id,
                                    "type": m_type,
                                    "description": item.get("description", "Kaggle TPU Model"),
                                })
            except Exception as e:
                logger.debug(f"Failed to query /v1/models on Kaggle: {e}")

        # If the server returned an empty list or didn't implement /v1/models,
        # provide the standard default Kaggle TPU model suite
        if not models:
            models = [
                {
                    "name": "Qwen/Qwen2.5-7B-Instruct",
                    "type": "language",
                    "description": "Dual-T4 accelerated LLM (Qwen2.5-7B-Instruct)",
                },
                {
                    "name": "kaggle-tpu-chat",
                    "type": "language",
                    "description": "Kaggle Dual-T4 LLM pipeline",
                },
                {
                    "name": "BAAI/bge-small-en-v1.5",
                    "type": "embedding",
                    "description": "High-throughput vector embeddings on Kaggle",
                },
                {
                    "name": "kaggle-tpu-embedding",
                    "type": "embedding",
                    "description": "Kaggle host vector embeddings",
                },
                {
                    "name": "kaggle-tpu-podcast",
                    "type": "text_to_speech",
                    "description": "Long-form Podcast multi-speaker TTS pipeline",
                },
                {
                    "name": "kaggle-tpu-stt",
                    "type": "speech_to_text",
                    "description": "Whisper Speech-to-Text transcription on Kaggle",
                },
            ]

        return models

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "kaggle-tpu-chat",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Execute synchronous chat completion on Kaggle TPU via /v1/chat/completions.
        """
        headers = self._get_headers()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **kwargs,
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.post(
                self._normalize_url("v1/chat/completions"),
                json=payload,
                headers=headers,
            )
            if resp.status_code != 200:
                error_body = resp.text
                logger.error(f"Kaggle chat completion failed ({resp.status_code}): {error_body}")
                raise RuntimeError(
                    f"Kaggle TPU chat completion returned HTTP {resp.status_code}: {error_body}"
                )
            return resp.json()

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "kaggle-tpu-chat",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Execute streaming chat completion on Kaggle TPU via SSE.
        """
        import json

        headers = self._get_headers()
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            async with client.stream(
                "POST",
                self._normalize_url("v1/chat/completions"),
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    err = await response.aread()
                    raise RuntimeError(f"Kaggle streaming failed ({response.status_code}): {err.decode('utf-8')}")

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def create_embeddings(
        self,
        texts: List[str],
        model: str = "kaggle-tpu-embedding",
    ) -> List[List[float]]:
        """
        Generate embeddings via /v1/embeddings on Kaggle.
        """
        if not texts:
            return []

        headers = self._get_headers()
        payload = {
            "model": model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.post(
                self._normalize_url("v1/embeddings"),
                json=payload,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.error(f"Kaggle embeddings failed ({resp.status_code}): {resp.text}")
                raise RuntimeError(f"Kaggle embeddings returned HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            data_items = result.get("data", [])
            # Sort by index if present
            data_items = sorted(data_items, key=lambda x: x.get("index", 0))
            return [item.get("embedding", []) for item in data_items]

    async def generate_podcast(
        self,
        content: str,
        briefing: str,
        episode_name: str,
        duration_minutes: int = 15,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Submit podcast generation request to Kaggle's /api/podcast.
        Supports both async job polling (prevents Cloudflare 100s tunnel timeout)
        and immediate synchronous responses.
        """
        import time

        headers = self._get_headers()
        payload = {
            "content": content,
            "briefing": briefing,
            "episode_name": episode_name,
            "duration_minutes": duration_minutes,
            "language": language,
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.post(
                self._normalize_url("api/podcast"),
                json=payload,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.error(f"Kaggle podcast generation failed ({resp.status_code}): {resp.text}")
                raise RuntimeError(
                    f"Kaggle podcast generation returned HTTP {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        # If server returned an async job_id, poll status every 2.5 seconds
        # Each poll request takes < 100ms, completely bypassing Cloudflare 100s timeout
        if "job_id" in data and data.get("status") in ["processing", "queued"]:
            job_id = data["job_id"]
            logger.info(f"Kaggle podcast job submitted: {job_id}. Polling progress...")
            start_poll = time.time()
            max_wait_seconds = 360.0

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                while time.time() - start_poll < max_wait_seconds:
                    await asyncio.sleep(2.5)
                    poll_resp = await client.get(
                        self._normalize_url(f"api/podcast/status/{job_id}"),
                        headers=headers,
                    )
                    if poll_resp.status_code != 200:
                        logger.warning(f"Polling podcast status returned HTTP {poll_resp.status_code}")
                        continue

                    job_info = poll_resp.json()
                    status = job_info.get("status")
                    if status == "completed":
                        logger.info(
                            f"Kaggle podcast job {job_id} completed successfully in {time.time() - start_poll:.1f}s"
                        )
                        return job_info.get("result", {})
                    elif status == "failed":
                        err_msg = job_info.get("error", "Unknown error")
                        logger.error(f"Kaggle podcast job {job_id} failed: {err_msg}")
                        raise RuntimeError(f"Kaggle podcast generation failed: {err_msg}")
                    else:
                        progress = job_info.get("progress", 0)
                        msg = job_info.get("message", "Processing")
                        logger.debug(f"Podcast job {job_id} [{progress * 100:.0f}%]: {msg}")

                raise TimeoutError(
                    f"Kaggle podcast job {job_id} exceeded maximum wait time ({max_wait_seconds}s)"
                )

        return data
