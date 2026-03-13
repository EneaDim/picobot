from __future__ import annotations


def short_status_from_runtime(msg, *, channel: str = "cli") -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "runtime.turn_started":
        return "📨 Received"

    if mtype == "runtime.telegram.voice_note.received":
        return "🎙 Voice received"

    if mtype == "runtime.telegram.voice_note.transcribed":
        return "🧠 Transcript ready"

    if mtype == "runtime.telegram.voice_note.normalized":
        return "🧭 Routing"

    if mtype == "runtime.turn.route_selected":
        action = str(payload.get("route_action") or "").strip()
        name = str(payload.get("route_name") or "").strip()
        if action and name:
            if action == "tool":
                return f"🧭 Route → tool:{name}"
            if action == "workflow":
                return f"🧭 Route → workflow:{name}"
            return f"🧭 Route → {action}:{name}"
        return "🧭 Routing…"

    if mtype == "runtime.retrieval.started":
        return "🔎 Retrieving context…"

    if mtype == "runtime.retrieval.completed":
        if payload.get("ok") is False:
            return "❌ Retrieval failed"
        return "🔎 Retrieval completed"

    if mtype == "runtime.turn.context_built":
        return "🧩 Context ready…"

    if mtype == "runtime.tool.started":
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name == "tts":
            return "🔊 Generating audio…"
        if tool_name == "stt":
            return "🎙 Transcribing audio…"
        if tool_name in {"yt_summary", "yt_transcript"}:
            return "📺 Processing YouTube content…"
        if tool_name == "python":
            return "🐍 Running Python…"
        if tool_name == "fetch":
            return "🌐 Fetching content…"
        if tool_name:
            return f"🛠 Running {tool_name}…"
        return "🛠 Running tool…"

    if mtype == "runtime.tool.completed":
        ok = payload.get("ok")
        return "✅ Tool completed" if ok is not False else "❌ Tool failed"

    if mtype == "runtime.tool.failed":
        return "❌ Tool failed"

    if mtype == "runtime.audio.generated":
        return "🎧 Audio ready"

    if mtype == "runtime.memory.updated":
        return "🧠 Updating memory…"

    if mtype == "runtime.turn_completed":
        return "✅ Completed"

    if mtype == "runtime.turn_failed":
        return "❌ Failed"

    return None


def debug_line_from_runtime(msg) -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "runtime.turn_started":
        return f"📥 turn     started    text_len={payload.get('text_len', '?')}"

    if mtype == "runtime.turn.route_selected":
        lines = [
            f"🧭 route    selected   {payload.get('route_action', '?')}:{payload.get('route_name', '?')}",
            f"   source={payload.get('route_source', '?')} score={payload.get('route_score', 0.0):.3f}",
        ]
        reason = payload.get("route_reason")
        if reason:
            lines.append(f"   reason={reason}")
        candidates = list(payload.get("route_candidates", []) or [])
        if candidates:
            lines.append("   candidates:")
            for item in candidates[:4]:
                lines.append(f"   - {item}")
        return "\n".join(lines)

    if mtype == "runtime.retrieval.started":
        return (
            f"🔎 retrieval started   kb={payload.get('kb_name', '?')} "
            f"top_k={payload.get('top_k', '?')}"
        )

    if mtype == "runtime.retrieval.completed":
        if payload.get("ok") is False:
            return f"❌ retrieval failed    error={payload.get('error', '?')}"
        return (
            f"🔎 retrieval done      hits={payload.get('hits', 0)} "
            f"context_chars={payload.get('context_chars', 0)}"
        )

    if mtype == "runtime.turn.context_built":
        return (
            f"🧩 context   built     workflow={payload.get('workflow_name', '?')} "
            f"history={payload.get('history_messages_count', 0)} "
            f"facts={payload.get('memory_facts_count', 0)} "
            f"summary={'yes' if payload.get('summary_present') else 'no'} "
            f"retrieval={'yes' if payload.get('retrieval_present') else 'no'}"
        )

    if mtype == "runtime.tool.started":
        return (
            f"🛠 tool      started   name={payload.get('tool_name', '?')} "
            f"workflow={payload.get('workflow_name', '?')}"
        )

    if mtype == "runtime.tool.completed":
        return (
            f"✅ tool      done      name={payload.get('tool_name', '?')} "
            f"ok={payload.get('ok', True)}"
        )

    if mtype == "runtime.tool.failed":
        return (
            f"❌ tool      failed    name={payload.get('tool_name', '?')} "
            f"error={payload.get('error', '?')}"
        )

    if mtype == "runtime.audio.generated":
        return f"🎧 audio     generated path={payload.get('audio_path', '?')}"

    if mtype == "runtime.memory.updated":
        return f"🧠 memory    updated   facts={payload.get('facts_count', '?')}"

    if mtype == "runtime.turn_completed":
        return (
            f"🏁 turn      completed action={payload.get('action', '?')} "
            f"reason={payload.get('reason', '?')} "
            f"provider={payload.get('provider_name', '-') or '-'} "
            f"hits={payload.get('retrieval_hits', 0)} "
            f"audio={'yes' if payload.get('has_audio') else 'no'}"
        )

    if mtype == "runtime.turn_failed":
        return f"❌ turn      failed    error={payload.get('error', '?')}"

    return None


def telegram_status_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return "⏳ Working…"
    return f"⏳ {text}"


def telegram_trace_footer(msgs: list[str]) -> str:
    lines = [m.strip() for m in msgs if str(m or "").strip()]
    if not lines:
        return ""
    return "Debug trace:\n" + "\n".join(f"• {line}" for line in lines[:8])
