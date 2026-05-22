from __future__ import annotations

import time
import logging
import requests
from threading import Lock
from typing import Optional
from urllib.parse import urlparse
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Session:
    def __init__(self, retry_count=3, retry_delay=1.5, timeout=30.0):
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self._timeout = timeout
        self._lock = Lock()
        self._session: Optional[requests.Session] = None

    def get(self, referer: str) -> requests.Session:
        with self._lock:
            if self._session is None:
                self._session = requests.Session()
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            self._session.headers.update(
                {
                    "User-Agent": UserAgent().chrome,
                    "Referer": referer,
                    "Origin": origin,
                }
            )
            return self._session

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        if self._session is None:
            raise RuntimeError("Session not initialised : call get() first")
        last_exc: Exception = RuntimeError("no attempts made")
        for attempt in range(1, self._retry_count + 1):
            try:
                resp = self._session.request(
                    method, url, timeout=self._timeout, **kwargs
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self._retry_count:
                    logger.warning(
                        "attempt %d/%d failed (%s), retrying in %.1fs",
                        attempt,
                        self._retry_count,
                        exc,
                        self._retry_delay,
                    )
                    time.sleep(self._retry_delay)
        raise last_exc

    def close(self):
        with self._lock:
            if self._session:
                self._session.close()
                self._session = None
