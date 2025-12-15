"""This file provides abstractions for interacting with various LLM backends."""

import asyncio
import dataclasses
import logging
import os
import time
from pathlib import Path
from typing import Any

import openai
from dataclasses import field

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types
from chem_scout_ai.common.util import ratelimit

logger = logging.getLogger(__name__)


_GOOGLE_OPENAI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GOOGLE_API_KEY_ENV_VAR = "GOOGLE_API_KEY"

_OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_OPENAI_API_KEY_ENV_VAR = "OPENAI_API_KEY"

_LLAMA_CPP_API_KEY_ENV_VAR = "LLAMA_CPP_API_KEY"


class LLMBackend:
    """
    Synchronous wrapper around OpenAI/Google chat models.
    """

    _client: openai.Client
    _model: str
    _ratelimiter: ratelimit.RateLimiter | None

    def __init__(
        self,
        *,
        client: openai.Client,
        model: str,
        ratelimiter: ratelimit.RateLimiter | None,
    ) -> None:
        self._client = client
        self._model = model
        self._ratelimiter = ratelimiter

    def __call__(
        self,
        *,
        response_format: type | None = None,
        **kwargs: Any,
    ) -> types.ModelResponse:
        """
        Calls the model.

        If response_format is provided → parse mode is used.
        Otherwise → regular chat completion.
        """
        if self._ratelimiter:
            with self._ratelimiter:
                return self._call_internal(response_format=response_format, **kwargs)
        return self._call_internal(response_format=response_format, **kwargs)

    def _call_internal(
        self,
        *,
        response_format: type | None = None,
        **kwargs: Any,
    ) -> types.ModelResponse:
        if response_format is not None:
            kwargs["response_format"] = response_format
            fn = self._client.chat.completions.parse
        else:
            fn = self._client.chat.completions.create
        return fn(model=self._model, **kwargs)

    def generate(
        self,
        chat: chat_lib.Chat,
        /,
        **kwargs: Any,
    ) -> types.ModelResponse:
        """
        Generates a new model response from a Chat object.
        """
        return self(messages=chat.messages, **kwargs)


class AsyncLLMBackend:
    """
    Asynchronous wrapper around OpenAI/Google chat models.
    """

    _client: openai.AsyncClient
    _model: str
    _ratelimiter: ratelimit.RateLimiter | None
    _fallback_configs: list["LLMBackendConfig"]
    _chat_store_dir: Path | None

    def __init__(
        self,
        *,
        client: openai.AsyncClient,
        model: str,
        ratelimiter: ratelimit.RateLimiter | None,
        fallbacks: list["LLMBackendConfig"] | None = None,
        chat_store_dir: Path | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._ratelimiter = ratelimiter
        self._fallback_configs = fallbacks or []
        self._chat_store_dir = chat_store_dir

    async def __call__(
        self,
        *,
        response_format: type | None = None,
        **kwargs: Any,
    ) -> types.ModelResponse:
        """
        Calls the model asynchronously.
        """

        if self._ratelimiter:
            with self._ratelimiter:
                return await self._call_internal(response_format=response_format, **kwargs)

        return await self._call_internal(response_format=response_format, **kwargs)

    async def _call_internal(
        self,
        *,
        response_format: type | None = None,
        **kwargs: Any,
    ) -> types.ModelResponse:
        if response_format is not None:
            kwargs["response_format"] = response_format
            fn = self._client.chat.completions.parse
        else:
            fn = self._client.chat.completions.create
        return await fn(model=self._model, **kwargs)

    async def generate(
        self,
        chat: chat_lib.Chat,
        /,
        **kwargs: Any,
    ) -> types.ModelResponse:
        try:
            return await self(messages=chat.messages, **kwargs)
        except openai.RateLimitError as err:
            return await self._handle_rate_limit(chat=chat, kwargs=kwargs, error=err)

    # ------------------------------------------------------------------
    # Rate limit handling
    # ------------------------------------------------------------------
    def _persist_chat(self, chat: chat_lib.Chat, reason: str) -> Path | None:
        if not self._chat_store_dir:
            return None

        try:
            self._chat_store_dir.mkdir(parents=True, exist_ok=True)
            safe_model = self._model.replace("/", "-")
            path = self._chat_store_dir / f"{int(time.time())}_{safe_model}_{reason}.json"
            with path.open("wb") as fp:
                chat.save(fp)
            logger.info("Saved chat history for retry: %s", path)
            return path
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to persist chat after rate limit")
            return None

    @staticmethod
    def _extract_retry_after(error: openai.RateLimitError) -> float | None:
        retry_after = getattr(error, "retry_after", None)
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except (TypeError, ValueError):
                pass

        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None) if response else None
        if headers:
            header_val = headers.get("retry-after") or headers.get("Retry-After")
            if header_val:
                try:
                    return max(float(header_val), 0.0)
                except (TypeError, ValueError):
                    return None
        return None

    async def _try_fallbacks(
        self,
        *,
        chat: chat_lib.Chat,
        kwargs: dict[str, Any],
    ) -> types.ModelResponse | None:
        for idx, cfg in enumerate(self._fallback_configs):
            if not cfg.is_free:
                continue
            if not cfg.api_key:
                logger.debug("Skipping fallback %s: missing API key", cfg.model_name)
                continue
            if cfg.model_name == self._model:
                continue

            remaining = self._fallback_configs[idx + 1 :]
            backend = cfg.get_async_backend(
                fallback_configs=remaining,
                chat_store_dir=self._chat_store_dir,
            )
            try:
                logger.info(
                    "Rate limit hit on %s, switching to free tier model %s",
                    self._model,
                    cfg.model_name,
                )
                return await backend.generate(chat, **kwargs)
            except openai.RateLimitError:
                logger.warning(
                    "Fallback model %s also rate-limited, trying next free model",
                    cfg.model_name,
                )
                continue
            except Exception:
                logger.exception(
                    "Fallback model %s failed, attempting next option", cfg.model_name
                )
                continue
        return None

    async def _handle_rate_limit(
        self,
        *,
        chat: chat_lib.Chat,
        kwargs: dict[str, Any],
        error: openai.RateLimitError,
    ) -> types.ModelResponse:
        self._persist_chat(chat, "rate-limit")

        retry_after = self._extract_retry_after(error)
        if retry_after is not None:
            logger.warning(
                "Rate limit for %s. Retrying after %.2f seconds.", self._model, retry_after
            )
            await asyncio.sleep(retry_after)
            try:
                return await self(messages=chat.messages, **kwargs)
            except openai.RateLimitError as err:
                error = err  # use latest error

        fallback_response = await self._try_fallbacks(chat=chat, kwargs=kwargs)
        if fallback_response is not None:
            return fallback_response

        # No fallback available → re-raise
        raise error


# -------------------------------------------------------------------------
# Backend configuration classes
# -------------------------------------------------------------------------

@dataclasses.dataclass(kw_only=True)
class LLMBackendConfig:
    """
    Base class for all backend configs.
    """

    name: str
    base_url: str
    model_name: str
    api_key: str | None = None
    ratelimit: float | None = None
    is_free: bool = False

    def get_backend(self) -> LLMBackend:
        client = openai.Client(base_url=self.base_url, api_key=self.api_key)
        rate = ratelimit.RateLimiter(self.ratelimit) if self.ratelimit else None
        return LLMBackend(client=client, model=self.model_name, ratelimiter=rate)

    def get_async_backend(
        self,
        *,
        fallback_configs: list["LLMBackendConfig"] | None = None,
        chat_store_dir: Path | None = None,
    ) -> AsyncLLMBackend:
        client = openai.AsyncClient(base_url=self.base_url, api_key=self.api_key)
        rate = ratelimit.RateLimiter(self.ratelimit) if self.ratelimit else None
        return AsyncLLMBackend(
            client=client,
            model=self.model_name,
            ratelimiter=rate,
            fallbacks=fallback_configs,
            chat_store_dir=chat_store_dir,
        )

    def get_async_client(self) -> tuple[openai.AsyncClient, str]:
        client = openai.AsyncClient(base_url=self.base_url, api_key=self.api_key)
        return client, self.model_name

    def get_client(self) -> tuple[openai.Client, str]:
        client = openai.Client(base_url=self.base_url, api_key=self.api_key)
        return client, self.model_name


# -------------------------------------------------------------------------
# Concrete Backends
# -------------------------------------------------------------------------

@dataclasses.dataclass(kw_only=True)
class Gemini2p5FlashLite(LLMBackendConfig):
    name: str = "Gemini 2.5 Flash Lite"
    base_url: str = _GOOGLE_OPENAI_API_BASE_URL
    model_name: str = "gemini-2.5-flash-lite"
    api_key: str | None = field(default_factory=lambda: os.environ.get(_GOOGLE_API_KEY_ENV_VAR))
    ratelimit: float | None = 15.
    is_free: bool = True


@dataclasses.dataclass(kw_only=True)
class Gemini2p5Flash(LLMBackendConfig):
    name: str = "Gemini 2.5 Flash"
    base_url: str = _GOOGLE_OPENAI_API_BASE_URL
    model_name: str = "gemini-2.5-flash"
    api_key: str | None = field(default_factory=lambda: os.environ.get(_GOOGLE_API_KEY_ENV_VAR))
    ratelimit: float | None = 10.


@dataclasses.dataclass(kw_only=True)
class Gemini2p5Pro(LLMBackendConfig):
    name: str = "Gemini 2.5 Pro"
    base_url: str = _GOOGLE_OPENAI_API_BASE_URL
    model_name: str = "gemini-2.5-pro"
    api_key: str | None = os.environ.get(_GOOGLE_API_KEY_ENV_VAR)
    ratelimit: float | None = 2.


@dataclasses.dataclass(kw_only=True)
class GPT5(LLMBackendConfig):
    name: str = "GPT-5"
    base_url: str = _OPENAI_API_BASE_URL
    model_name: str = "gpt-5"
    api_key: str | None = os.environ.get(_OPENAI_API_KEY_ENV_VAR)


@dataclasses.dataclass(kw_only=True)
class LLamaCpp(LLMBackendConfig):
    name: str = "llama.cpp"
    base_url: str = ""
    model_name: str = "model"
    api_key: str | None = os.environ.get(_LLAMA_CPP_API_KEY_ENV_VAR, "sk-")


BACKENDS = {Gemini2p5FlashLite, Gemini2p5Flash, Gemini2p5Pro, GPT5, LLamaCpp}
BACKENDS_ENTRY = {backend.name: backend for backend in BACKENDS}
