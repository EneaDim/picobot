from __future__ import annotations


def kb_user_prompt(*, lang: str, question: str, context: str) -> str:
    q = (question or "").strip()
    ctx = (context or "").strip()

    if (lang or "").lower().startswith("it"):
        return (
            "Rispondi in ITALIANO usando SOLO il contesto fornito qui sotto.\n"
            "\n"
            "Regole obbligatorie:\n"
            "1. Usa solo informazioni supportate dal contesto.\n"
            "2. Non inventare dettagli mancanti.\n"
            "3. Non usare frasi come 'si può dedurre', 'probabilmente', 'potrebbe essere' salvo che l'utente chieda esplicitamente un'inferenza.\n"
            "4. Se l'informazione NON è presente nel contesto, scrivi esattamente: 'Questa informazione non è presente nel contesto fornito.'\n"
            "5. Se la risposta è presente nel contesto, rispondi in modo diretto e concreto.\n"
            "6. Se il contesto contiene una lista o una definizione esplicita, riportala fedelmente in forma parafrasata.\n"
            "7. Non cambiare lingua.\n"
            "8. Non parlare del tuo processo interno.\n"
            "\n"
            "Formato desiderato:\n"
            "- Risposta breve e precisa.\n"
            "- Se la domanda richiede elenco o punti, usa punti numerati.\n"
            "\n"
            f"DOMANDA:\n{q}\n"
            "\n"
            "CONTESTO:\n"
            f"{ctx}\n"
        ).strip()

    return (
        "Answer in ENGLISH using ONLY the provided context below.\n"
        "\n"
        "Mandatory rules:\n"
        "1. Use only information supported by the context.\n"
        "2. Do not invent missing details.\n"
        "3. Do not use phrases like 'it can be inferred', 'probably', or 'it might be' unless the user explicitly asked for an inference.\n"
        "4. If the information is NOT present in the context, write exactly: 'This information is not present in the provided context.'\n"
        "5. If the answer is present, respond directly and concretely.\n"
        "6. If the context contains an explicit list or definition, reproduce it faithfully in paraphrased form.\n"
        "7. Do not switch language.\n"
        "8. Do not discuss your internal process.\n"
        "\n"
        "Preferred format:\n"
        "- Short and precise answer.\n"
        "- If the question asks for a list, use numbered points.\n"
        "\n"
        f"QUESTION:\n{q}\n"
        "\n"
        "CONTEXT:\n"
        f"{ctx}\n"
    ).strip()
