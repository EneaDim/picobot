from __future__ import annotations


def tool_protocol_system(tool_names: list[str]) -> str:
    """
    Prompt sistema per forzare un protocollo JSON minimale di tool calling.
    """
    tools = ", ".join(tool_names) if tool_names else "(none)"
    return (
        "You may answer normally OR emit a JSON tool request.\n"
        "Allowed tools: " + tools + "\n\n"
        "If you want to call a tool, output ONLY valid JSON in one of these forms:\n"
        '{"tool":"tool_name","arguments":{"key":"value"}}\n'
        "or\n"
        '{"tool_calls":[{"name":"tool_name","arguments":{"key":"value"}}]}\n'
        "If no tool is needed, answer in plain text.\n"
    )
