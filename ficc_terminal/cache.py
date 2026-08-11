from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import HttpPayload


class OfficialHttpClient:
    """HTTP client that retains the last successful raw official response.

    A failed download never causes the application to invent a value. If a cached
    official response exists, it is returned with ``stale=True`` and the UI labels
    it accordingly.
    """

    def __init__(self, cache_dir: str | Path = "data/raw", timeout: int = 15) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": "FICC-Morning-Call-Educational-Project/1.0",
                "Accept": "*/*",
            }
        )

    def _paths(self, key: str) -> tuple[Path, Path]:
        safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
        return self.cache_dir / f"{safe_key}.raw", self.cache_dir / f"{safe_key}.meta.json"

    def _save(self, key: str, response: requests.Response) -> HttpPayload:
        raw_path, meta_path = self._paths(key)
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw_path.write_bytes(response.content)
        metadata = {
            "retrieved_at": retrieved_at,
            "url": response.url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return HttpPayload(
            content=response.content,
            retrieved_at=retrieved_at,
            from_cache=False,
            stale=False,
            cache_path=str(raw_path),
            content_type=metadata["content_type"],
            response_headers=dict(response.headers),
        )

    def _load_cached(self, key: str) -> HttpPayload:
        raw_path, meta_path = self._paths(key)
        if not raw_path.exists() or not meta_path.exists():
            raise FileNotFoundError(f"No cached response exists for {key}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        return HttpPayload(
            content=raw_path.read_bytes(),
            retrieved_at=metadata["retrieved_at"],
            from_cache=True,
            stale=True,
            cache_path=str(raw_path),
            content_type=metadata.get("content_type"),
            response_headers=metadata,
        )

    def get(
        self,
        key: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpPayload:
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._save(key, response)
        except (requests.RequestException, OSError):
            return self._load_cached(key)

    def post_json(
        self,
        key: str,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> HttpPayload:
        try:
            response = self.session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._save(key, response)
        except (requests.RequestException, OSError):
            return self._load_cached(key)

