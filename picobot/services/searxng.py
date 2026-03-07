from __future__ import annotations

# Managed local SearXNG service.
#
# Obiettivi:
# - health check HTTP
# - start automatico via docker compose
# - restart automatico base
# - errori sintetici e leggibili
#
# Questa classe NON deve esportare stacktrace Docker all'utente finale.
# Deve fare best effort locale-first e poi fallire in modo chiaro.
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


class SearxngError(RuntimeError):
    """
    Errore base del service layer SearXNG.
    """


class SearxngUnavailableError(SearxngError):
    """
    SearXNG non disponibile dopo i tentativi di recovery.
    """


@dataclass(frozen=True)
class SearxngSearchItem:
    title: str
    url: str
    description: str
    source: str = ""


class SearxngManager:
    """
    Gestore del servizio locale SearXNG.
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg

        web_cfg = getattr(cfg, "web", None)

        self.enabled = bool(getattr(web_cfg, "enabled", True))
        self.base_url = str(getattr(web_cfg, "searxng_url", "http://localhost:8080") or "http://localhost:8080").rstrip("/")

        # Nuovi campi opzionali: se non esistono nello schema attuale,
        # getattr(...) li gestisce in modo sicuro.
        self.managed = bool(getattr(web_cfg, "managed_searxng", True))
        self.health_timeout_s = float(getattr(web_cfg, "health_timeout_s", 2.5) or 2.5)
        self.startup_timeout_s = float(getattr(web_cfg, "startup_timeout_s", 45.0) or 45.0)
        self.auto_restart_on_failure = bool(getattr(web_cfg, "auto_restart_on_failure", True))
        self.max_results = int(getattr(web_cfg, "max_results", 5) or 5)

        self.compose_dir = self._resolve_compose_dir(
            str(getattr(web_cfg, "docker_compose_dir", "searxng") or "searxng")
        )
        self.compose_service_name = str(getattr(web_cfg, "docker_service_name", "searxng") or "searxng")

    # ------------------------------------------------------------------
    # Path / command helpers
    # ------------------------------------------------------------------

    def _resolve_compose_dir(self, value: str) -> Path:
        """
        Risolve la directory del docker compose di SearXNG.

        Se il path è relativo, lo interpretiamo rispetto alla root del repo.
        """
        path = Path(value).expanduser()
        if path.is_absolute():
            return path

        repo_root = Path(__file__).resolve().parents[2]
        return (repo_root / path).resolve()

    def _compose_cmd_prefix(self) -> list[str]:
        """
        Ritorna il comando compose disponibile nel sistema.
        """
        if shutil.which("docker") is not None:
            return ["docker", "compose"]

        if shutil.which("docker-compose") is not None:
            return ["docker-compose"]

        raise SearxngUnavailableError("Docker Compose non disponibile nel sistema locale")

    def _run_compose(self, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
        """
        Esegue docker compose nella directory di SearXNG.
        """
        cmd = [*self._compose_cmd_prefix(), *args]

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.compose_dir),
                text=True,
                capture_output=True,
                check=check,
            )
        except FileNotFoundError as e:
            raise SearxngUnavailableError("Docker o Docker Compose non trovato") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            detail = stderr or stdout or str(e)
            raise SearxngUnavailableError(f"docker compose failed: {detail}") from e

        return proc

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """
        True se il servizio risponde via HTTP.
        """
        if not self.enabled:
            return False

        urls = [
            self.base_url,
            f"{self.base_url}/search?q=test&format=json",
        ]

        for url in urls:
            try:
                with httpx.Client(timeout=self.health_timeout_s, follow_redirects=True) as client:
                    res = client.get(url)
                    if res.status_code < 500:
                        return True
            except Exception:
                continue

        return False

    def wait_ready(self, timeout_s: float | None = None) -> bool:
        """
        Attende che SearXNG diventi pronto.
        """
        deadline = time.time() + float(timeout_s or self.startup_timeout_s)

        while time.time() < deadline:
            if self.is_ready():
                return True
            time.sleep(1.0)

        return False

    # ------------------------------------------------------------------
    # Docker lifecycle
    # ------------------------------------------------------------------

    def logs_tail(self, lines: int = 120) -> str:
        """
        Restituisce la coda log della compose app SearXNG.
        """
        try:
            proc = self._run_compose(
                ["logs", "--tail", str(int(lines)), self.compose_service_name],
                check=False,
            )
            text = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            return text[-6000:].strip()
        except Exception as e:
            return f"(unable to fetch searxng logs: {e})"

    def start(self) -> None:
        """
        Avvio best effort del servizio.
        """
        if not self.managed:
            return

        if not self.compose_dir.exists():
            raise SearxngUnavailableError(
                f"directory compose SearXNG non trovata: {self.compose_dir}"
            )

        proc = self._run_compose(["up", "-d"], check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise SearxngUnavailableError(f"impossibile avviare SearXNG: {detail}")

    def restart(self) -> None:
        """
        Restart semplice del bundle compose.
        """
        if not self.managed:
            return

        # down best-effort
        try:
            self._run_compose(["down"], check=False)
        except Exception:
            pass

        self.start()

    def ensure_ready(self) -> None:
        """
        Garantisce che il servizio sia disponibile.
        """
        if not self.enabled:
            raise SearxngUnavailableError("servizio web disabilitato in configurazione")

        if self.is_ready():
            return

        if not self.managed:
            raise SearxngUnavailableError(
                "SearXNG non raggiungibile e managed_searxng è disabilitato"
            )

        # Primo tentativo: up -d + wait
        self.start()
        if self.wait_ready(self.startup_timeout_s):
            return

        # Secondo tentativo: restart completo
        if self.auto_restart_on_failure:
            self.restart()
            if self.wait_ready(self.startup_timeout_s):
                return

        logs = self.logs_tail(80)
        short = logs[-1800:].strip() if logs else "no logs available"

        raise SearxngUnavailableError(
            "il servizio web locale non è riuscito ad avviarsi.\n"
            f"Dettaglio:\n{short}"
        )

    # ------------------------------------------------------------------
    # Search API
    # ------------------------------------------------------------------

    def search(
        self,
        *,
        query: str,
        count: int | None = None,
        categories: str = "general",
        language: str = "auto",
    ) -> list[SearxngSearchItem]:
        """
        Ricerca via API JSON di SearXNG.
        """
        self.ensure_ready()

        q = (query or "").strip()
        if not q:
            return []

        limit = max(1, int(count or self.max_results))

        params = {
            "q": q,
            "format": "json",
            "categories": categories,
            "language": language,
        }

        try:
            with httpx.Client(timeout=float(getattr(self.cfg.web, "timeout_s", 10.0) or 10.0), follow_redirects=True) as client:
                res = client.get(f"{self.base_url}/search", params=params)
                res.raise_for_status()
                data = res.json()
        except httpx.TimeoutException as e:
            raise SearxngUnavailableError("timeout durante la query a SearXNG") from e
        except httpx.HTTPError as e:
            raise SearxngUnavailableError(f"errore HTTP da SearXNG: {e}") from e
        except Exception as e:
            raise SearxngUnavailableError(f"errore durante la query a SearXNG: {e}") from e

        raw_results = list((data or {}).get("results") or [])
        out: list[SearxngSearchItem] = []
        seen_urls: set[str] = set()

        for item in raw_results:
            if not isinstance(item, dict):
                continue

            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            desc = str(item.get("content") or item.get("snippet") or "").strip()
            source = str(item.get("engine") or item.get("source") or "").strip()

            if not url or url in seen_urls:
                continue

            seen_urls.add(url)

            out.append(
                SearxngSearchItem(
                    title=title or url,
                    url=url,
                    description=desc,
                    source=source,
                )
            )

            if len(out) >= limit:
                break

        return out
