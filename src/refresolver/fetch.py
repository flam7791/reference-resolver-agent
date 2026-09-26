"""JSON over HTTP with a disk cache that doubles as a recorder for replayable evaluations.

- Every successful response is stored under cache_dir/http, keyed by the full URL.
- In offline mode the cache is the only source: a missing entry raises CacheMiss instead of
  calling the network. Recording once and replaying later makes evaluations reproducible and
  lets CI run them without network access or API costs.
- Politeness: an identifying User-Agent with a contact address when configured, a minimum
  interval between calls to the same host, and bounded retries on 429 and 5xx.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from . import __version__
from .config import Settings

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MIN_INTERVAL_SECONDS = 0.15  # at most about 6 requests per second per host


class FetchError(RuntimeError):
    """The service failed after retries."""


class CacheMiss(FetchError):
    """Offline mode and no recorded response for this request."""


class JsonFetcher:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.root = settings.cache_dir / "http"
        agent = f"reference-resolver-agent/{__version__}"
        if settings.contact_email:
            agent += f" (mailto:{settings.contact_email})"
        self.headers = {"User-Agent": agent}
        self.client = client or httpx.Client(timeout=settings.http_timeout)
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def _path(self, url: str) -> Path:
        return self.root / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def get_json(self, base_url: str, params: dict | None = None) -> dict | None:
        """GET a JSON document. Returns None for 404 (for example an unregistered DOI)."""
        url = base_url + ("?" + urlencode(sorted(params.items())) if params else "")
        path = self._path(url)
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            return record["body"]
        if self.settings.offline:
            raise CacheMiss(f"Offline and no recorded response for {url}")

        body = self._fetch(url)
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "body": body}), encoding="utf-8")
        return body

    def _wait_turn(self, host: str) -> None:
        with self._lock:
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_call.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            self._last_call[host] = time.monotonic()

    def _fetch(self, url: str) -> dict | None:
        host = urlsplit(url).netloc
        for attempt in range(1, 4):
            self._wait_turn(host)
            log.info("GET %s", url)
            try:
                response = self.client.get(url, headers=self.headers)
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise FetchError(f"Network error for {host}: {exc}") from exc
                time.sleep(attempt)
                continue
            if response.status_code == 404:
                return None
            if response.status_code in RETRY_STATUSES and attempt < 3:
                retry_after = response.headers.get("Retry-After", "")
                time.sleep(min(float(retry_after), 10.0) if retry_after.isdigit() else 2.0**attempt)
                continue
            if response.status_code >= 400:
                raise FetchError(f"{host} returned HTTP {response.status_code}")
            return response.json()
        raise FetchError(f"{host} kept failing after retries")
