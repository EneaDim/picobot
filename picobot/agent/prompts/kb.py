from __future__ import annotations

def kb_user_prompt(*, lang: str, question: str, context: str) -> str:
    """
    Prompt utente per risposte grounded su KB.
    """
    q = (question or "").strip()
    ctx = (context or "").strip()

    if str(lang).lower().startswith("en"):
        return (
            "Answer the user using ONLY the context below.\n"
            "If the context is insufficient, say so clearly.\n"
            "Do not invent facts.\n\n"
            f"QUESTION:\n{q}\n\n"
            f"CONTEXT:\n{ctx}\n"
        )

    return (
        "Rispondi usando SOLO il contesto qui sotto.\n"
        "Se il contesto non basta, dillo chiaramente.\n"
        "Non inventare fatti.\n\n"
        f"DOMANDA:\n{q}\n\n"
        f"CONTESTO:\n{ctx}\n"
    )
