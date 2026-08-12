"""
Blue Robot LLM Client
=====================
Handles communication with LM Studio (local LLM).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests

from .utils import log

# ================================================================================
# CONFIGURATION
# ================================================================================

LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")
LM_STUDIO_RAG_URL = "http://127.0.0.1:1234/v1/rag"


# ================================================================================
# SETTINGS
# ================================================================================

@dataclass
class Settings:
    """Application settings."""
    LOG_LEVEL: str = "INFO"
    MAX_ITERATIONS: int = 10
    TOOL_TIMEOUT_SECS: float = 15.0
    TOOL_RETRIES: int = 2
    MAX_CONTEXT_MESSAGES: int = 20
    AUTO_DOCSEARCH_MODE: str = "opt_in"


settings = Settings()


# ================================================================================
# ABANDONABLE TRANSPORT
# ================================================================================

def stream_abandonable(
    url: str,
    payload: Dict[str, Any],
    timeout: float,
    should_cancel: Callable[[], bool],
) -> Dict[str, Any]:
    """Stream a completion, dropping it the moment the caller says to.

    Assembled into exactly what a blocking call returns, so callers see no
    difference apart from the extra ``cancelled`` outcome. Cancellation is
    checked per streamed line: a reasoning model emits them steadily, so the
    model is handed back within a token of the request. Measured against
    LM Studio: a live turn arriving 2s into a 17s reflection waited 16.9s
    without this and 0.7s with it.

    There is no retry loop — an abandoned background job is requeued by its
    owner, and retrying a call that was cancelled for being in the way would
    put it straight back in the way.

    Reasoning deltas are accumulated separately and returned under
    ``reasoning_content``, matching the blocking response shape: a reflection's
    JSON sometimes lands inside the think block, and the parser looks there.

    Lives at module scope because there are two LMStudioClient classes — this
    one and the older copy in bluetools.py, which is the one the chat pipeline
    actually calls. Both delegate here rather than carrying two copies that
    could drift.
    """
    payload = {**payload, "stream": True}
    parts: List[str] = []
    reasoning: List[str] = []
    finish_reason = None
    try:
        with requests.post(url, json=payload,
                           timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for raw in response.iter_lines():
                if should_cancel():
                    # Closing the connection is what actually stops the
                    # generation; returning early alone would leave the model
                    # busy for the foreground caller we just yielded to.
                    response.close()
                    return {"cancelled": True,
                            "partial_chars": sum(len(p) for p in parts)}
                if not raw or not raw.startswith(b"data: "):
                    continue
                body = raw[6:].strip()
                if body == b"[DONE]":
                    break
                try:
                    chunk = json.loads(body)
                except ValueError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
    except Exception as exc:
        return {"error": f"LLM stream failed: {exc}"}

    message: Dict[str, Any] = {"role": "assistant", "content": "".join(parts)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    return {"choices": [{"message": message,
                         "finish_reason": finish_reason or "stop"}]}


# ================================================================================
# LM STUDIO CLIENT
# ================================================================================

class LMStudioClient:
    """
    Enhanced client for local LM Studio (OpenAI-compatible) chat completions.
    Features:
    - Auto-retry with exponential backoff
    - Connection health checks
    - Request/response logging
    - Timeout management
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3
    ):
        self.base_url = base_url or LM_STUDIO_URL
        self.model = model or LM_STUDIO_MODEL
        self.timeout = float(timeout or os.environ.get("LM_STUDIO_TIMEOUT", "120"))
        self.max_retries = max_retries
        self._healthy = None
        self._last_health_check = 0

    def is_healthy(self, force_check: bool = False) -> bool:
        """Check if LM Studio is responding (cached for 60s)."""
        now = time.time()
        if not force_check and self._healthy is not None and (now - self._last_health_check) < 60:
            return self._healthy

        try:
            health_url = self.base_url.replace('/chat/completions', '/models')
            resp = requests.get(health_url, timeout=5)
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False

        self._last_health_check = now
        return self._healthy

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Send a chat completion request to LM Studio.

        ``should_cancel`` makes the call abandonable: it is polled while the
        reply streams in and, when it goes true, the connection is dropped so
        the model stops generating and is free for whoever asked for it. The
        caller gets ``{"cancelled": True}`` and no reply. It is declared here
        rather than left to **kwargs because everything in kwargs is sent to
        LM Studio as a payload field.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if extra and isinstance(extra, dict):
            payload.update(extra)
        if kwargs:
            payload.update(kwargs)

        if should_cancel is not None:
            return self._chat_abandonable(payload, should_cancel)

        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(self.base_url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                result = resp.json()

                if 'choices' not in result and 'error' not in result:
                    raise ValueError(f"Unexpected response structure: {list(result.keys())}")

                return result

            except requests.exceptions.Timeout as e:
                last_error = e
                wait_time = 2 ** attempt
                log.warning(f"[LLM] Timeout on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)

            except requests.exceptions.ConnectionError as e:
                last_error = e
                wait_time = 2 ** attempt
                log.warning(f"[LLM] Connection error on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)

            except requests.exceptions.HTTPError as e:
                if e.response.status_code < 500:
                    return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
                last_error = e
                wait_time = 2 ** attempt
                log.warning(f"[LLM] Server error on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)

            except Exception as e:
                last_error = e
                log.error(f"[LLM] Unexpected error: {e}")
                break

        return {"error": f"LLM request failed after {self.max_retries} attempts: {last_error}"}

    def _chat_abandonable(
        self,
        payload: Dict[str, Any],
        should_cancel: Callable[[], bool],
    ) -> Dict[str, Any]:
        return stream_abandonable(self.base_url, payload, self.timeout,
                                  should_cancel)


# ================================================================================
# GLOBAL CLIENT
# ================================================================================

_lm_client: Optional[LMStudioClient] = None


def get_lm_client() -> Optional[LMStudioClient]:
    """Get or create the global LM Studio client."""
    global _lm_client
    if _lm_client is None:
        try:
            _lm_client = LMStudioClient()
        except Exception as e:
            log.warning(f"Failed to init LM Studio client: {e}")
    return _lm_client


def call_llm(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    include_tools: bool = True,
    tool_choice: str = "auto",
    force_tool: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Unified LLM entrypoint: always uses local LM Studio.

    Args:
        messages: List of conversation messages
        tools: List of tool definitions (optional)
        include_tools: Whether to include tools in the request
        tool_choice: Tool selection mode ("auto", "none", or specific tool)
        force_tool: If set, nudge the model to use this specific tool
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature
        extra: Additional parameters to pass to the API
        **kwargs: Additional keyword arguments

    Returns:
        API response dictionary
    """
    client = get_lm_client()
    if client is None:
        return {"error": "LM Studio client not available"}

    # Nudge if a specific tool is required
    if force_tool:
        messages = list(messages)
        if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
            messages[-1] = {**messages[-1]}
            messages[-1]["content"] = (
                (messages[-1].get("content") or "")
                + "\n\n[System note: Use the specified tool to satisfy this request.]"
            )

    tools_payload = tools if include_tools and tools else None

    try:
        return client.chat(
            messages,
            tools=tools_payload,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            **kwargs
        )
    except Exception as e:
        return {"error": f"LM Studio request failed: {e}"}


# Initialize client on import
_lm_client = get_lm_client()
