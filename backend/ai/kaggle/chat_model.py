"""
LangChain BaseChatModel adapter for Kaggle TPU.

Enables seamless execution inside LangGraph workflows (Notebook Chat, Source Chat,
Ask, Transformations, Flashcards) by bridging LangChain's BaseMessage protocol
to the Kaggle TPU backend.
"""

import asyncio
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from loguru import logger
from pydantic import Field

from backend.ai.kaggle.client import KaggleClient


def _convert_message_to_dict(message: BaseMessage) -> Dict[str, str]:
    """Convert a LangChain message into an OpenAI-compatible role/content dict."""
    if isinstance(message, ChatMessage):
        role = message.role
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    elif isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, (FunctionMessage, ToolMessage)):
        role = "function"
    else:
        role = "user"

    content = message.content
    if isinstance(content, list):
        # Flatten multi-part content (e.g., text blocks)
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(part["text"])
        content_str = "\n".join(text_parts)
    else:
        content_str = str(content)

    return {"role": role, "content": content_str}


class KaggleChatModel(BaseChatModel):
    """LangChain BaseChatModel implementation targeting the Kaggle TPU."""

    base_url: str = Field(..., description="Kaggle server tunnel URL")
    api_key: Optional[str] = Field(default=None, description="Optional Kaggle access token")
    model_name: str = Field(default="kaggle-tpu-chat", description="Model identifier on Kaggle")
    temperature: float = Field(default=0.2, description="Sampling temperature")
    max_tokens: int = Field(default=8192, description="Maximum tokens to generate")
    timeout: float = Field(default=90.0, description="HTTP timeout in seconds")

    _client: Optional[KaggleClient] = None

    def __init__(self, **data: Any):
        super().__init__(**data)
        self._client = KaggleClient(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    @property
    def _llm_type(self) -> str:
        return "kaggle-tpu-chat"

    @property
    def client(self) -> KaggleClient:
        if self._client is None:
            self._client = KaggleClient(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous chat generation."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    self._agenerate(messages, stop=stop, run_manager=None, **kwargs),
                )
                return future.result()
        else:
            return loop.run_until_complete(
                self._agenerate(messages, stop=stop, run_manager=None, **kwargs)
            )

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Asynchronous chat generation directly via Kaggle TPU."""
        formatted_messages = [_convert_message_to_dict(m) for m in messages]
        merged_kwargs = {**kwargs}
        if stop:
            merged_kwargs["stop"] = stop

        resp = await self.client.chat_completion(
            messages=formatted_messages,
            model=self.model_name,
            temperature=merged_kwargs.get("temperature", self.temperature),
            max_tokens=merged_kwargs.get("max_tokens", self.max_tokens),
            **merged_kwargs,
        )

        choices = resp.get("choices", [])
        if not choices:
            raise RuntimeError("Empty completion returned from Kaggle TPU backend")

        first_choice = choices[0]
        content = first_choice.get("message", {}).get("content", "")
        finish_reason = first_choice.get("finish_reason", "stop")

        ai_message = AIMessage(
            content=content,
            response_metadata={
                "finish_reason": finish_reason,
                "model_name": self.model_name,
                "usage": resp.get("usage", {}),
            },
        )

        generation = ChatGeneration(
            message=ai_message,
            generation_info={"finish_reason": finish_reason},
        )
        return ChatResult(generations=[generation])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Stream response chunks from Kaggle TPU."""
        formatted_messages = [_convert_message_to_dict(m) for m in messages]
        merged_kwargs = {**kwargs}
        if stop:
            merged_kwargs["stop"] = stop

        async for chunk_text in self.client.stream_chat_completion(
            messages=formatted_messages,
            model=self.model_name,
            temperature=merged_kwargs.get("temperature", self.temperature),
            max_tokens=merged_kwargs.get("max_tokens", self.max_tokens),
            **merged_kwargs,
        ):
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=chunk_text)
            )
            if run_manager:
                await run_manager.on_llm_new_token(chunk_text, chunk=chunk)
            yield chunk

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Synchronous streaming wrapper."""
        async def _collect():
            chunks = []
            async for c in self._astream(messages, stop=stop, **kwargs):
                chunks.append(c)
            return chunks

        chunks = asyncio.run(_collect())
        for c in chunks:
            yield c
