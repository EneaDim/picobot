from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from picobot.agent.agents.base import AgentResult
from picobot.agent.prompts import (
    youtube_summarizer_system,
    youtube_summarizer_user_prompt,
    news_summarizer_system,
    news_summarizer_user_prompt,
    news_json_repair_system,
    news_json_repair_user_prompt,
    system_base_context,
)
from picobot.providers.ollama import OllamaProvider


Kind = Literal["generic", "youtube", "news"]


def _clean_title(title: str, url: str = "") -> str:
    t = (title or "").strip()
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\s*[›|»-]\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|›»")
    t = re.sub(r"\b(it|en|fr|de|es|cs|da|bg)\b\s*", "", t, flags=re.I).strip()
    if len(t) < 8 and url:
        t = url
    return t or "Notizia"


def _sentences(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[\.\!\?])\s+", t)
    out = []
    for p in parts:
        p = p.strip(" -•\t\r\n")
        if len(p) < 30:
            continue
        low = p.lower()
        if "schema.org" in low or "seleziona la tua lingua" in low or "cambia la lingua" in low:
            continue
        if "<a href" in low or "{" in p or "}" in p:
            continue
        out.append(p.rstrip(".") + ".")
    return out


def _dedupe_points(points: list[str]) -> list[str]:
    out = []
    seen = set()
    for p in points:
        norm = re.sub(r"\s+", " ", p.lower()).strip()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(p)
    return out


def _three_points(it: dict[str, Any], lang: str) -> list[str]:
    desc = (it.get("description") or "").strip()
    snippet = (it.get("snippet") or "").strip()
    text = (it.get("text") or "").strip()

    pool = []
    for part in [desc, snippet]:
        if part:
            pool.append(part.rstrip(".") + ".")

    for s in _sentences(text):
        pool.append(s)
        if len(pool) >= 8:
            break

    pool = _dedupe_points(pool)

    if len(pool) == 0:
        pool.append("Dettagli non completamente disponibili nella fonte." if lang == "it" else "Details not fully available in the source.")
    if len(pool) == 1:
        pool.append("La fonte evidenzia implicazioni rilevanti sul tema trattato." if lang == "it" else "The source highlights relevant implications.")
    if len(pool) == 2:
        pool.append("Il contenuto conferma la rilevanza della notizia nel contesto considerato." if lang == "it" else "The content confirms the relevance of the news item.")

    return pool[:3]


def _format_news_fallback(lang: str, query: str, items: list[dict[str, Any]]) -> str:
    header = f"### News Digest: {query}" if query else "### News Digest"
    lines = [header, ""]

    kept = 0
    for idx, it in enumerate(items[:5], start=1):
        if not isinstance(it, dict) or not it.get("ok"):
            continue

        url = (it.get("final_url") or it.get("url") or "").strip()
        title = _clean_title((it.get("title") or "").strip(), url)
        points = _three_points(it, lang)

        lines.append(f"{idx}. {title}")
        for p in points:
            lines.append(f"   - {p}")
        if url:
            lines.append(f"   Fonte: {url}" if lang == "it" else f"   Source: {url}")
        lines.append("")
        kept += 1

    if kept == 0:
        return "Nessuna notizia utile trovata." if lang == "it" else "No useful news found."
    return "\n".join(lines).strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    if not t:
        return None

    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r'(\{[\s\S]*\})', t)
    if not m:
        return None
    chunk = m.group(1)

    try:
        obj = json.loads(chunk)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def _normalize_news_json(obj: dict[str, Any], lang: str) -> dict[str, Any]:
    raw_items = obj.get("items") or []
    out_items = []

    if not isinstance(raw_items, list):
        return {"items": []}

    for it in raw_items[:5]:
        if not isinstance(it, dict):
            continue

        title = str(it.get("title") or "").strip()
        source_url = str(it.get("source_url") or it.get("url") or "").strip()
        bullets = it.get("bullets") or []

        if not isinstance(bullets, list):
            bullets = []

        bullets = [str(x).strip() for x in bullets if str(x).strip()]
        bullets = _dedupe_points(bullets)

        if len(bullets) < 3:
            continue

        out_items.append(
            {
                "title": title or ("Notizia" if lang == "it" else "News item"),
                "bullets": bullets[:3],
                "source_url": source_url,
            }
        )

    return {"items": out_items[:5]}


def _render_news_json(lang: str, query: str, obj: dict[str, Any]) -> str:
    header = f"### News Digest: {query}" if query else "### News Digest"
    lines = [header, ""]

    items = obj.get("items") or []
    if not isinstance(items, list) or not items:
        return "Nessuna notizia utile trovata." if lang == "it" else "No useful news found."

    for idx, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        bullets = it.get("bullets") or []
        source_url = str(it.get("source_url") or "").strip()

        lines.append(f"{idx}. {title}")
        for b in bullets[:3]:
            lines.append(f"   - {str(b).strip()}")
        if source_url:
            lines.append(f"   Fonte: {source_url}" if lang == "it" else f"   Source: {source_url}")
        lines.append("")

    return "\n".join(lines).strip()


def _debug_enabled() -> bool:
    return str(os.environ.get("PICOBOT_NEWS_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}


def _dump_debug(name: str, content: str) -> None:
    if not _debug_enabled():
        return
    d = Path(".picobot/debug")
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content or "", encoding="utf-8")


@dataclass
class SummarizerAgent:
    provider: OllamaProvider
    name: str = "summarizer"

    async def run(self, *, input_text: Any, lang: str, memory_ctx: str, kind: Kind = "generic") -> AgentResult:
        base = system_base_context(lang) + "\n" + (memory_ctx or "")

        if kind == "youtube":
            sys = youtube_summarizer_system()
            usr = youtube_summarizer_user_prompt(
                transcript=str(input_text or ""),
                url="",
                lang=lang,
                max_chars=12000,
            )
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base + "\n" + sys},
                    {"role": "user", "content": usr},
                ],
                tools=None,
                max_tokens=650,
                temperature=0.0,
            )
            return AgentResult(name=self.name, ok=True, text=(resp.content or "").strip(), data={})

        if kind == "news":
            query = ""
            items: list[dict[str, Any]] = []

            if isinstance(input_text, dict):
                query = str(input_text.get("query") or "")
                raw_items = input_text.get("items") or []
                if isinstance(raw_items, list):
                    items = [x for x in raw_items if isinstance(x, dict)]
            elif isinstance(input_text, list):
                items = [x for x in input_text if isinstance(x, dict)]
            elif isinstance(input_text, str):
                txt = input_text.strip()
                if txt:
                    try:
                        parsed = json.loads(txt)
                        if isinstance(parsed, dict):
                            query = str(parsed.get("query") or "")
                            raw_items = parsed.get("items") or []
                            if isinstance(raw_items, list):
                                items = [x for x in raw_items if isinstance(x, dict)]
                        elif isinstance(parsed, list):
                            items = [x for x in parsed if isinstance(x, dict)]
                    except Exception:
                        pass

            # pass 1: ask for JSON
            resp1 = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base + "\n" + news_summarizer_system()},
                    {"role": "user", "content": news_summarizer_user_prompt(lang=lang, query=query, items=items, max_bullets=5)},
                ],
                tools=None,
                max_tokens=900,
                temperature=0.0,
            )
            raw1 = (resp1.content or "").strip()
            _dump_debug("news_pass1.txt", raw1)

            parsed1 = _extract_json(raw1)
            if parsed1:
                norm1 = _normalize_news_json(parsed1, lang)
                if (norm1.get("items") or []):
                    rendered = _render_news_json(lang, query, norm1)
                    return AgentResult(name=self.name, ok=True, text=rendered, data=norm1)

            # pass 2: repair malformed output
            resp2 = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base + "\n" + news_json_repair_system()},
                    {"role": "user", "content": news_json_repair_user_prompt(raw1)},
                ],
                tools=None,
                max_tokens=700,
                temperature=0.0,
            )
            raw2 = (resp2.content or "").strip()
            _dump_debug("news_pass2_repair.txt", raw2)

            parsed2 = _extract_json(raw2)
            if parsed2:
                norm2 = _normalize_news_json(parsed2, lang)
                if (norm2.get("items") or []):
                    rendered = _render_news_json(lang, query, norm2)
                    return AgentResult(name=self.name, ok=True, text=rendered, data=norm2)

            rendered = _format_news_fallback(lang, query, items)
            return AgentResult(name=self.name, ok=True, text=rendered, data={})

        resp = await self.provider.chat(
            messages=[
                {"role": "system", "content": base + "\n" + system_base_context(lang)},
                {"role": "user", "content": str(input_text or "")},
            ],
            tools=None,
            max_tokens=650,
            temperature=0.0,
        )
        return AgentResult(name=self.name, ok=True, text=(resp.content or "").strip(), data={})
