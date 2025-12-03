"""This file provides abstractions for interacting with various LLM backends."""

import dataclasses
import os
from typing import Any

import openai

from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types
from chem_scout_ai.common.util import ratelimit


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

    def __init__(
        self,
        *,
        client: openai.AsyncClient,
        model: str,
        ratelimiter: ratelimit.RateLimiter | None,
    ) -> None:
        self._client = client
        self._model = model
        self._ratelimiter = ratelimiter

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
        return await self(messages=chat.messages, **kwargs)


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

    def get_backend(self) -> LLMBackend:
        client = openai.Client(base_url=self.base_url, api_key=self.api_key)
        rate = ratelimit.RateLimiter(self.ratelimit) if self.ratelimit else None
        return LLMBackend(client=client, model=self.model_name, ratelimiter=rate)

    def get_async_backend(self) -> AsyncLLMBackend:
        client = openai.AsyncClient(base_url=self.base_url, api_key=self.api_key)
        rate = ratelimit.RateLimiter(self.ratelimit) if self.ratelimit else None
        return AsyncLLMBackend(client=client, model=self.model_name, ratelimiter=rate)

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
    api_key: str | None = os.environ.get(_GOOGLE_API_KEY_ENV_VAR)
    ratelimit: float | None = 15.


@dataclasses.dataclass(kw_only=True)
class Gemini2p5Flash(LLMBackendConfig):
    name: str = "Gemini 2.5 Flash"
    base_url: str = _GOOGLE_OPENAI_API_BASE_URL
    model_name: str = "gemini-2.5-flash"
    api_key: str | None = os.environ.get(_GOOGLE_API_KEY_ENV_VAR)
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
