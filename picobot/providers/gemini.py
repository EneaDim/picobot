from __future__ import annotations

import json
import os
from typing import Any

import httpx

from picobot.providers.types import ChatResponse, ToolCall


class GeminiProviderError(Exception):
    pass


class GeminiTimeout(GeminiProviderError):
    pass


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _coerce_tool_calls(raw: Any) -> list[ToolCall]:
    out: list[ToolCall] = []

    if raw is None:
        return out

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("tool") or "").strip()
            arguments = item.get("arguments") or {}
            if not name:
                continue
            if not isinstance(arguments, dict):
                arguments = {}
            out.append(ToolCall(name=name, arguments=arguments))
        return out

    if isinstance(raw, dict) and isinstance(raw.get("tool_calls"), list):
        return _coerce_tool_calls(raw.get("tool_calls"))

    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("tool") or "").strip()
        arguments = raw.get("arguments") or {}
        if name:
            if not isinstance(arguments, dict):
                arguments = {}
            out.append(ToolCall(name=name, arguments=arguments))
        return out

    return out


class GeminiProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "GEMINI_API_KEY",
        timeout_s: float = 120.0,
        default_max_tokens: int = 1200,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.model = str(model or "").strip()
        self.api_key_env = str(api_key_env or "GEMINI_API_KEY").strip()
        self.timeout_s = float(timeout_s or 120.0)
        self.default_max_tokens = int(default_max_tokens or 1200)
        self.base_url = str(base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

        if not self.model:
            raise ValueError("Gemini model must not be empty")

    def _api_key(self) -> str:
        value = os.environ.get(self.api_key_env, "").strip()
        if not value:
            raise GeminiProviderError(f"Missing API key env: {self.api_key_env}")
        return value

    def _resolve_max_tokens(self, max_tokens: int | None) -> int:
        value = int(max_tokens or self.default_max_tokens or 1200)
        return value if value > 0 else 1200

    def _to_gemini_contents(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = str(msg.get("role") or "user").strip().lower()
            text = str(msg.get("content") or "").strip()
            if not text:
                continue

            gemini_role = "user"
            if role == "assistant":
                gemini_role = "model"

            contents.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": text}],
                }
            )
        return contents

    def _extract_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not isinstance(candidates, list):
            return ""

        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            content = cand.get("content") or {}
            parts = content.get("parts") or []
            if not isinstance(parts, list):
                continue
            out: list[str] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    out.append(text.strip())
            if out:
                return "\n".join(out).strip()

        return ""

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> ChatResponse:
        msg_list = list(messages or [])
        if not msg_list:
            raise GeminiProviderError("messages must not be empty")

        payload = {
            "contents": self._to_gemini_contents(msg_list),
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": self._resolve_max_tokens(max_tokens),
            },
        }

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key(),
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            raise GeminiTimeout(f"Gemini timed out after {self.timeout_s}s") from e
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                body = ""
            raise GeminiProviderError(
                f"Gemini HTTP error {e.response.status_code}: {body or str(e)}"
            ) from e
        except Exception as e:
            raise GeminiProviderError(str(e)) from e

        if not isinstance(data, dict):
            raise GeminiProviderError("Gemini returned a non-object JSON response")

        raw_content = self._extract_text(data)

        # Per ora manteniamo compatibilità: niente function-calling reale.
        parsed = _safe_json_loads(raw_content)
        tool_calls = _coerce_tool_calls(parsed)

        if not tool_calls:
            return ChatResponse(content=raw_content, tool_calls=[])

        return ChatResponse(content="", tool_calls=tool_calls)
