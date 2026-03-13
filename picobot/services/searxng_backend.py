from __future__ import annotations

import re
import shutil
import subprocess
import time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx

from picobot.runtime_config import cfg_get
from picobot.services.search_backend import SearchResult, WebSearchUnavailableError


class SearxngBackend:
    """
    Backend SearXNG usato solo internamente.
    """

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg

        self.enabled = bool(self._cfg("web_search.enabled", True))
        self.base_url = str(self._cfg("web_search.searxng_url", "http://localhost:8080") or "http://localhost:8080").rstrip("/")
        self.timeout_s = float(self._cfg("web_search.timeout_s", 10.0) or 10.0)
        self.max_results = int(self._cfg("web_search.max_results", 5) or 5)

        self.managed = bool(self._cfg("web_search.managed_backend", True))
        self.health_timeout_s = float(self._cfg("web_search.health_timeout_s", 2.5) or 2.5)
        self.startup_timeout_s = float(self._cfg("web_search.startup_timeout_s", 45.0) or 45.0)
        self.auto_restart_on_failure = bool(self._cfg("web_search.auto_restart_on_failure", True))

        self.compose_dir = self._resolve_compose_dir(
            str(self._cfg("web_search.docker_compose_dir", "searxng") or "searxng")
        )
        self.compose_service_name = str(self._cfg("web_search.docker_service_name", "searxng") or "searxng")

    def _cfg(self, path: str, default):
        if self.cfg is not None:
            current = self.cfg
            for part in path.split("."):
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return cfg_get(path, default)
            return current
        return cfg_get(path, default)

    def _resolve_compose_dir(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        repo_root = Path(__file__).resolve().parents[2]
        return (repo_root / path).resolve()

    def _compose_cmd_prefix(self) -> list[str]:
        if shutil.which("docker") is not None:
            return ["docker", "compose"]
        if shutil.which("docker-compose") is not None:
            return ["docker-compose"]
        raise WebSearchUnavailableError("Docker Compose non disponibile nel sistema locale")

    def _run_compose(self, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
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
            raise WebSearchUnavailableError("Docker o Docker Compose non trovato") from e
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            stdout = (e.stdout or "").strip()
            detail = stderr or stdout or str(e)
            raise WebSearchUnavailableError(f"docker compose failed: {detail}") from e
        return proc

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PicobotLocalSearch/1.0)",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Accept-Language": "it,en;q=0.8",
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
            },
        )

    def is_ready(self) -> bool:
        if not self.enabled:
            return False

        urls = [
            self.base_url,
            f"{self.base_url}/search?q=test&format=json",
        ]

        for url in urls:
            try:
                with self._client(self.health_timeout_s) as client:
                    res = client.get(url)
                    if res.status_code < 500:
                        return True
            except Exception:
                continue

        return False

    def wait_ready(self, timeout_s: float | None = None) -> bool:
        deadline = time.time() + float(timeout_s or self.startup_timeout_s)
        while time.time() < deadline:
            if self.is_ready():
                return True
            time.sleep(1.0)
        return False

    def logs_tail(self, lines: int = 120) -> str:
        try:
            proc = self._run_compose(
                ["logs", "--tail", str(int(lines)), self.compose_service_name],
                check=False,
            )
            text = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            return text[-6000:].strip()
        except Exception as e:
            return f"(unable to fetch backend logs: {e})"

    def start(self) -> None:
        if not self.managed:
            return

        if not self.compose_dir.exists():
            raise WebSearchUnavailableError(
                f"directory compose del backend search non trovata: {self.compose_dir}"
            )

        proc = self._run_compose(["up", "-d"], check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise WebSearchUnavailableError(f"impossibile avviare il backend search locale: {detail}")

    def restart(self) -> None:
        if not self.managed:
            return
        try:
            self._run_compose(["down"], check=False)
        except Exception:
            pass
        self.start()

    def ensure_ready(self) -> None:
        if not self.enabled:
            raise WebSearchUnavailableError("servizio di ricerca web disabilitato in configurazione")

        if self.is_ready():
            return

        if not self.managed:
            raise WebSearchUnavailableError(
                "backend di ricerca web non raggiungibile e managed_backend è disabilitato"
            )

        self.start()
        if self.wait_ready(self.startup_timeout_s):
            return

        if self.auto_restart_on_failure:
            self.restart()
            if self.wait_ready(self.startup_timeout_s):
                return

        logs = self.logs_tail(80)
        short = logs[-1800:].strip() if logs else "no logs available"

        raise WebSearchUnavailableError(
            "il backend di ricerca web locale non è riuscito ad avviarsi.\n"
            f"Dettaglio:\n{short}"
        )

    def _request_search_json(self, *, query: str, category: str, language: str):
        params = {
            "q": query,
            "format": "json",
            "categories": category,
            "language": language,
        }
        with self._client(self.timeout_s) as client:
            return client.get(f"{self.base_url}/search", params=params)

    def _request_search_html(self, *, query: str, category: str, language: str):
        params = {
            "q": query,
            "categories": category,
            "language": language,
        }
        with self._client(self.timeout_s) as client:
            return client.get(f"{self.base_url}/search", params=params)

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value or "")
        text = unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _parse_html_results(self, html: str, *, limit: int) -> list[SearchResult]:
        text = html or ""
        out: list[SearchResult] = []
        seen: set[str] = set()

        anchor_re = re.compile(
            r'<a[^>]+class="[^"]*result__url[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        title_re = re.compile(
            r'<h3[^>]*class="[^"]*result_header[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>.*?</h3>',
            re.IGNORECASE | re.DOTALL,
        )
        content_re = re.compile(
            r'<p[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</p>',
            re.IGNORECASE | re.DOTALL,
        )
        engine_re = re.compile(
            r'<span[^>]+class="[^"]*engines[^"]*"[^>]*>(.*?)</span>',
            re.IGNORECASE | re.DOTALL,
        )

        urls = anchor_re.findall(text)
        titles = title_re.findall(text)
        contents = content_re.findall(text)
        engines = engine_re.findall(text)

        for idx, match in enumerate(urls):
            raw_url, raw_url_label = match
            url = unescape(raw_url.strip())
            if not url:
                continue
            url = urljoin(self.base_url + "/", url)
            if url in seen:
                continue
            seen.add(url)

            title = ""
            if idx < len(titles):
                title = self._strip_html(titles[idx])
            if not title:
                title = self._strip_html(raw_url_label) or url

            description = self._strip_html(contents[idx]) if idx < len(contents) else ""
            source = self._strip_html(engines[idx]) if idx < len(engines) else ""

            out.append(
                SearchResult(
                    title=title,
                    url=url,
                    description=description,
                    source=source,
                )
            )
            if len(out) >= limit:
                break

        return out

    def _load_results(self, res: httpx.Response, *, query: str, category: str, language: str, limit: int):
        if res.status_code == 403:
            try:
                html_res = self._request_search_html(query=query, category=category, language=language)
                if html_res.status_code < 400:
                    parsed = self._parse_html_results(html_res.text, limit=limit)
                    if parsed:
                        return {"results": [
                            {
                                "title": item.title,
                                "url": item.url,
                                "content": item.description,
                                "engine": item.source,
                            }
                            for item in parsed
                        ]}
            except Exception:
                pass

            if self.managed and self.auto_restart_on_failure:
                self.restart()
                if self.wait_ready(self.startup_timeout_s):
                    retry = self._request_search_json(query=query, category=category, language=language)
                    if retry.status_code != 403:
                        retry.raise_for_status()
                        return retry.json()

            detail = (res.text or "").strip()
            if len(detail) > 500:
                detail = detail[:500] + "..."

            logs = self.logs_tail(60)
            short_logs = logs[-1200:].strip() if logs else "no logs available"

            raise WebSearchUnavailableError(
                "backend di ricerca web locale raggiungibile ma ha rifiutato la query JSON (HTTP 403).\n"
                "Controlla la configurazione SearXNG locale, in particolare formato JSON / limiter / bot detection.\n"
                f"Dettaglio: {detail or 'forbidden'}\n"
                f"Logs recenti:\n{short_logs}"
            )

        res.raise_for_status()
        return res.json()

    def search(
        self,
        *,
        query: str,
        count: int | None = None,
        category: str = "general",
        language: str = "auto",
    ) -> list[SearchResult]:
        self.ensure_ready()

        q = (query or "").strip()
        if not q:
            return []

        limit = max(1, int(count or self.max_results))

        try:
            res = self._request_search_json(query=q, category=category, language=language)
            data = self._load_results(res, query=q, category=category, language=language, limit=limit)
        except WebSearchUnavailableError:
            raise
        except httpx.TimeoutException as e:
            raise WebSearchUnavailableError("timeout durante la query al backend di ricerca web") from e
        except httpx.HTTPError as e:
            raise WebSearchUnavailableError(f"errore HTTP dal backend di ricerca web: {e}") from e
        except Exception as e:
            raise WebSearchUnavailableError(f"errore durante la query al backend di ricerca web: {e}") from e

        raw_results = list((data or {}).get("results") or [])
        out: list[SearchResult] = []
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
                SearchResult(
                    title=title or url,
                    url=url,
                    description=desc,
                    source=source,
                )
            )

            if len(out) >= limit:
                break

        return out
