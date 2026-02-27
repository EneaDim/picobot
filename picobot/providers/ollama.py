from __future__ import annotations

import json
import httpx

from picobot.providers.types import ChatResponse, ToolCall


class OllamaProviderError(Exception):
    pass


class OllamaTimeout(OllamaProviderError):
    pass


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> ChatResponse:
        # If no tools: do NOT force JSON tool protocol. Let Ollama respond normally.
        if not tools:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    r = await client.post(f"{self.base_url}/api/chat", json=payload)
                    r.raise_for_status()
                    data = r.json()
            except httpx.TimeoutException as e:
                raise OllamaTimeout(f"Ollama timed out after {self.timeout_s}s") from e
            except Exception as e:
                raise OllamaProviderError(str(e)) from e

            raw = (data.get("message") or {}).get("content") or ""
            return ChatResponse(content=raw.strip(), tool_calls=[])

        # Tools enabled: use minimal JSON tool protocol
        tool_names = [t["function"]["name"] for t in (tools or [])]

        sys_tooling = (
            "You are a tool-using assistant.\n"
            "If you need to call a tool, respond with ONLY a JSON object like:\n"
            "{\"type\":\"tool\",\"name\":\"TOOL_NAME\",\"args\":{...}}\n"
            "If you are answering the user, respond with ONLY a JSON object like:\n"
            "{\"type\":\"final\",\"content\":\"...\"}\n"
            "Rules:\n"
            "- Output must be valid JSON.\n"
            "- TOOL_NAME must be one of: " + ", ".join(tool_names) + "\n"
        )

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": sys_tooling}] + messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.TimeoutException as e:
            raise OllamaTimeout(f"Ollama timed out after {self.timeout_s}s") from e
        except Exception as e:
            raise OllamaProviderError(str(e)) from e

        raw = (data.get("message") or {}).get("content") or ""
        raw = raw.strip()

        try:
            obj = json.loads(raw)
        except Exception:
            return ChatResponse(content=raw, tool_calls=[])

        if isinstance(obj, dict) and obj.get("type") == "tool":
            name = str(obj.get("name") or "").strip()
            args = obj.get("args")
            if not isinstance(args, dict):
                args = {}
            return ChatResponse(content="", tool_calls=[ToolCall(name=name, arguments=args)])

        if isinstance(obj, dict) and obj.get("type") == "final":
            return ChatResponse(content=str(obj.get("content") or "").strip(), tool_calls=[])

        return ChatResponse(content=raw, tool_calls=[])
