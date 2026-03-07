from __future__ import annotations

# Registry tool unico e compatibile.
#
# Obiettivi:
# - API semplice
# - accesso stabile a self.tools
# - compatibilità con codice che usa:
#   - registry.register(...)
#   - registry.get(...)
#   - registry.resolve_name(...)
#   - registry.list()
#   - registry.tools
#
# Questa versione evita mismatch tra implementazioni vecchie e nuove.
from picobot.tools.base import ToolSpec


class ToolRegistry:
    """
    Registro in-memory dei tool.
    """

    def __init__(self) -> None:
        # Importante: manteniamo questo attributo pubblico perché
        # parte del codice legacy/ibrido si aspetta registry.tools.
        self.tools: dict[str, ToolSpec] = {}

        # Alias/canonical names semplici.
        self.aliases: dict[str, str] = {}

    def register(self, spec: ToolSpec, aliases: list[str] | None = None) -> None:
        """
        Registra un tool e opzionali alias.
        """
        if not isinstance(spec, ToolSpec):
            raise TypeError(f"expected ToolSpec, got {type(spec)!r}")

        name = str(spec.name or "").strip()
        if not name:
            raise ValueError("tool spec name must not be empty")

        self.tools[name] = spec

        for alias in aliases or []:
            a = str(alias or "").strip()
            if a:
                self.aliases[a] = name

    def resolve_name(self, name: str) -> str:
        """
        Risolve un nome tool considerando alias.
        """
        raw = str(name or "").strip()
        if not raw:
            raise KeyError("empty tool name")

        return self.aliases.get(raw, raw)

    def get(self, name: str) -> ToolSpec:
        """
        Restituisce il ToolSpec risolto.
        """
        resolved = self.resolve_name(name)

        if resolved not in self.tools:
            raise KeyError(f"unknown tool: {name}")

        return self.tools[resolved]

    def has(self, name: str) -> bool:
        """
        True se il tool esiste.
        """
        try:
            resolved = self.resolve_name(name)
        except Exception:
            return False

        return resolved in self.tools

    def list(self) -> list[str]:
        """
        Elenco ordinato dei tool canonici registrati.
        """
        return sorted(self.tools.keys())

    def specs(self) -> list[ToolSpec]:
        """
        Elenco ToolSpec ordinato per nome.
        """
        return [self.tools[name] for name in self.list()]
