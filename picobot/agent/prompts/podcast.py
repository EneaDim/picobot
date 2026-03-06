from __future__ import annotations

def podcast_script_system_prompt(lang: str) -> str:
    """
    Prompt sistema per copioni podcast.
    """
    if str(lang).lower().startswith("en"):
        return (
            "You are a technical podcast writer.\n"
            "Write a short, natural, clear script with no markdown.\n"
            "Keep it compact, concrete, and pleasant to listen to.\n"
        )

    return (
        "Sei un autore di podcast tecnico.\n"
        "Scrivi un copione breve, naturale, chiaro, senza markdown.\n"
        "Mantieni il tono piacevole, concreto e facile da ascoltare.\n"
    )


def podcast_script_user_prompt(topic: str, lang: str, minutes: int, words_per_minute: int) -> str:
    """
    Prompt utente per copioni podcast.
    """
    topic = (topic or "").strip() or "podcast"
    minutes = max(1, int(minutes))
    target_words = max(80, minutes * max(80, int(words_per_minute)))

    if str(lang).lower().startswith("en"):
        return (
            f"Topic: {topic}\n"
            f"Target duration: about {minutes} minute(s)\n"
            f"Target words: about {target_words}\n\n"
            "Structure:\n"
            "- short opening\n"
            "- main explanation\n"
            "- short closing\n"
            "No markdown.\n"
        )

    return (
        f"Argomento: {topic}\n"
        f"Durata target: circa {minutes} minuto/i\n"
        f"Parole target: circa {target_words}\n\n"
        "Struttura:\n"
        "- apertura breve\n"
        "- spiegazione principale\n"
        "- chiusura breve\n"
        "Niente markdown.\n"
    )
