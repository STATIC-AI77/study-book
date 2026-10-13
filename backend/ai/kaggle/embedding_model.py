"""
Embedding model adapter for Kaggle TPU / Host CPU.

Provides embedding generation compatible with StudyBook's vector utilities
(backend/utils/embedding.py) and SurrealDB's vector search index.
"""

import asyncio
from typing import Any, List, Optional
from loguru import logger
from pydantic import BaseModel, Field

from backend.ai.kaggle.client import KaggleClient


class KaggleEmbeddingModel(BaseModel):
    """Embedding model adapter querying the Kaggle TPU backend."""

    base_url: str = Field(..., description="Kaggle server tunnel URL")
    api_key: Optional[str] = Field(default=None, description="Optional Kaggle access token")
    model_name: str = Field(default="kaggle-tpu-embedding", description="Embedding model name")
    timeout: float = Field(default=60.0, description="HTTP timeout in seconds")

    _client: Optional[KaggleClient] = None

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._client = KaggleClient(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    @property
    def client(self) -> KaggleClient:
        if self._client is None:
            self._client = KaggleClient(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    async def aembed(self, texts: List[str]) -> List[List[float]]:
        """
        Asynchronously generate embeddings for a batch of texts.
        Called directly by backend/utils/embedding.py during document ingestion.
        """
        if not texts:
            return []
        return await self.client.create_embeddings(texts, model=self.model_name)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Synchronous embedding call."""
        return asyncio.run(self.aembed(texts))

    async def aembed_query(self, text: str) -> List[float]:
        """Embed a single query string asynchronously."""
        res = await self.aembed([text])
        return res[0] if res else []

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string synchronously."""
        return asyncio.run(self.aembed_query(text))

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """LangChain compatible async document embedding."""
        return await self.aembed(texts)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """LangChain compatible sync document embedding."""
        return self.embed(texts)
