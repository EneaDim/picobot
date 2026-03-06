from __future__ import annotations

# Il router usa lo stesso provider embedding della KB.
#
# Non vogliamo due implementazioni separate:
# - una per retrieval documentale
# - una per router retrieval
#
# Questo wrapper esiste solo per preservare una separazione di package
# pulita e leggibile, ma sotto delega alla stessa implementazione.

from picobot.retrieval.embedder import LocalEmbedder

__all__ = ["LocalEmbedder"]
