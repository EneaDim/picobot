from __future__ import annotations

# Provider Ollama locale, pulito e robusto.
#
# Obiettivi:
# - una sola implementazione chiara per /api/chat
# - timeout ed errori leggibili
# - supporto normale a chat testuale
# - supporto opzionale a "tool protocol" JSON minimale
#
# Nota:
# l'orchestrator nuovo usa quasi sempre chat senza tools.
# Manteniamo però il ramo tools per compatibilità futura.
import json
from typing import Any

import httpx

from picobot.agent.prompts import tool_protocol_system
from picobot.providers.types import ChatResponse, ToolCall


class OllamaProviderError(Exception):
    """
    Errore generico del provider Ollama.
    """


class OllamaTimeout(OllamaProviderError):
    """
    Timeout specifico del provider Ollama.
    """


def _safe_json_loads(text: str) -> Any:
    """
    json.loads sicuro.
    """
    try:
        return json.loads(text)
    except Exception:
        return None


def _coerce_tool_calls(raw: Any) -> list[ToolCall]:
    """
    Interpreta un payload JSON minimale come lista di tool calls.

    Formati supportati:
    - {"tool_calls":[{"name":"x","arguments":{...}}]}
    - {"tool":"x","arguments":{...}}
    - [{"name":"x","arguments":{...}}]
    """
    out: list[ToolCall] = []

    if raw is None:
        return out

    # Caso 1: lista diretta di tool calls.
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

    # Caso 2: dict con chiave tool_calls.
    if isinstance(raw, dict) and isinstance(raw.get("tool_calls"), list):
        return _coerce_tool_calls(raw.get("tool_calls"))

    # Caso 3: dict singolo con tool / arguments.
    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("tool") or "").strip()
        arguments = raw.get("arguments") or {}
        if name:
            if not isinstance(arguments, dict):
                arguments = {}
            out.append(ToolCall(name=name, arguments=arguments))
        return out

    return out


class OllamaProvider:
    """
    Client minimale per Ollama locale.
    """

    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self.model = (model or "").strip()
        self.timeout_s = float(timeout_s or 120.0)

        if not self.model:
            raise ValueError("Ollama model must not be empty")

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Esegue POST su /api/chat e valida la risposta base.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as e:
            raise OllamaTimeout(f"Ollama timed out after {self.timeout_s}s") from e
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                body = ""
            raise OllamaProviderError(
                f"Ollama HTTP error {e.response.status_code}: {body or str(e)}"
            ) from e
        except Exception as e:
            raise OllamaProviderError(str(e)) from e

        if not isinstance(data, dict):
            raise OllamaProviderError("Ollama returned a non-object JSON response")

        return data

    def _extract_message_content(self, data: dict[str, Any]) -> str:
        """
        Estrae il contenuto testuale principale.
        """
        message = data.get("message") or {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()

        # fallback storico
        content = data.get("response")
        if isinstance(content, str):
            return content.strip()

        return ""

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> ChatResponse:
        """
        Chat principale contro Ollama.

        Se tools è vuoto:
        - normale conversazione

        Se tools è presente:
        - prepende un system prompt minimale
        - si aspetta eventualmente JSON con tool call
        """
        msg_list = list(messages or [])

        if not msg_list:
            raise OllamaProviderError("messages must not be empty")

        # Ramo normale: niente tool protocol.
        if not tools:
            payload = {
                "model": self.model,
                "messages": msg_list,
                "stream": False,
                "options": {
                    "temperature": float(temperature),
                    "num_predict": int(max_tokens),
                },
            }

            data = await self._post_chat(payload)
            content = self._extract_message_content(data)

            return ChatResponse(
                content=content,
                tool_calls=[],
            )

        # Ramo tools: protocollo JSON minimale.
        tool_names: list[str] = []

        for item in tools:
            try:
                fn = item.get("function") or {}
                name = str(fn.get("name") or "").strip()
                if name:
                    tool_names.append(name)
            except Exception:
                continue

        sys_tooling = tool_protocol_system(tool_names)

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": sys_tooling}] + msg_list,
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }

        data = await self._post_chat(payload)
        raw_content = self._extract_message_content(data)

        # Se il modello restituisce JSON tool protocol, lo interpretiamo.
        parsed = _safe_json_loads(raw_content)
        tool_calls = _coerce_tool_calls(parsed)

        # Se non c'è JSON valido, trattiamo tutto come testo normale.
        if not tool_calls:
            return ChatResponse(
                content=raw_content,
                tool_calls=[],
            )

        return ChatResponse(
            content="",
            tool_calls=tool_calls,
        )
