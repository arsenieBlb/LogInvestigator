"""Small vendor-independent model boundary; no provider receives local credentials as data."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class ProviderError(RuntimeError):
    """Safe, credential-free provider failure."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = "call_1"


@dataclass
class ProviderResponse:
    content: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = "unknown"
    response_id: str | None = None
    limit_reached: str | None = None


class Provider(Protocol):
    """Implementations return tool requests or a structured investigation draft."""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        schema: dict[str, Any],
        *,
        max_output_tokens: int,
        final: bool = False,
    ) -> ProviderResponse: ...


class ReplayProvider:
    """Deterministic scripted responses for protocol tests, explicitly never a live model.

    A callable step may inspect preceding tool *results*. The default application
    replay uses this to render a fixed rule-generated response from actual MCP data.
    Arbitrary exception steps make provider failures reproducible offline.
    """

    def __init__(
        self,
        steps: Sequence[
            ProviderResponse | Exception | Callable[[list[dict[str, Any]]], ProviderResponse]
        ],
    ) -> None:
        self.steps = list(steps)
        self.calls = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        schema: dict[str, Any],
        *,
        max_output_tokens: int,
        final: bool = False,
    ) -> ProviderResponse:
        if self.calls >= len(self.steps):
            raise ProviderError("replay script exhausted")
        step = self.steps[self.calls]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        response = step(messages) if callable(step) else step
        response.model = "deterministic-replay-v1"
        return response


class OpenRouterProvider:
    """Official OpenRouter Chat Completions tool calling and JSON schema output.

    The endpoint is fixed intentionally: model-controlled inputs cannot redirect
    credentials or enable network/shell tools. An injected transport is test-only.
    """

    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_response_bytes: int = 262_144,
    ) -> None:
        self.model = model or os.environ.get("LOG_INVESTIGATOR_MODEL", "openai/gpt-4.1-mini")
        if not self.model or len(self.model) > 200 or "preview" in self.model.lower():
            raise ValueError("a supported stable model identifier is required")
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        self.timeout = timeout
        self.transport = transport
        self.max_response_bytes = max_response_bytes

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        schema: dict[str, Any],
        *,
        max_output_tokens: int,
        final: bool = False,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": 0,
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        if final:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "investigation",
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        # Provider bodies may echo request material. Keep only status.
                        raise ProviderError(f"OpenRouter HTTP {response.status_code}")
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > self.max_response_bytes:
                            raise ProviderError("OpenRouter response byte limit exceeded")
            body = json.loads(raw)
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                usage = body.get("usage", {})
                return ProviderResponse(
                    usage=usage if isinstance(usage, dict) else {},
                    model=str(body.get("model", self.model))[:200],
                    response_id=str(body.get("id", ""))[:200] or None,
                    limit_reached="model_output_tokens",
                )
            if choice.get("error") or body.get("error"):
                raise ProviderError("OpenRouter returned a provider error")
            message = choice["message"]
            calls = [
                ToolCall(
                    name=call["function"]["name"],
                    arguments=json.loads(call["function"]["arguments"]),
                    call_id=call["id"],
                )
                for call in message.get("tool_calls", [])
            ]
            content = message.get("content")
            parsed = json.loads(content) if content and final else None
            if parsed is not None and not isinstance(parsed, dict):
                raise ProviderError("model response must be a JSON object")
            if any(not isinstance(call.arguments, dict) for call in calls):
                raise ProviderError("model tool arguments must be JSON objects")
            usage = body.get("usage", {})
            return ProviderResponse(
                content=parsed,
                tool_calls=calls,
                usage=usage if isinstance(usage, dict) else {},
                model=str(body.get("model", self.model))[:200],
                response_id=str(body.get("id", ""))[:200] or None,
            )
        except ProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError("OpenRouter request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("OpenRouter transport failed") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("OpenRouter returned invalid structured output") from exc
