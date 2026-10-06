"""Cliente HTTP 'educado' para fontes de terceiros: User-Agent identificado, robots.txt, limite por host,
cache condicional (ETag / If-Modified-Since) e retry com backoff."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from radar.collectors.base import CollectorError
from radar.settings import HttpConfig

log = logging.getLogger(__name__)


@dataclass
class HttpResult:
    url: str
    status: int
    content: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


class PoliteHttp:
    def __init__(self, cfg: HttpConfig, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 max_retries: int = 2):
        self.cfg, self._sleep, self._clock, self.max_retries = cfg, sleep, clock, max_retries
        self._client = client or httpx.Client(timeout=cfg.timeout_seconds, follow_redirects=True)
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}   # host -> (expira, parser|None=bloqueia tudo)

    @property
    def _ua_token(self) -> str:
        return self.cfg.user_agent.split("/")[0].split()[0]

    def _throttle(self, host: str) -> None:
        wait = self._last_hit.get(host, -1e9) + self.cfg.min_delay_seconds - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_hit[host] = self._clock()

    def _raw_get(self, url: str, headers: dict) -> httpx.Response:
        self._throttle(urlsplit(url).netloc)
        return self._client.get(url, headers={"User-Agent": self.cfg.user_agent, **headers})

    # -- robots.txt -------------------------------------------------------------
    def allowed(self, url: str) -> bool:
        if not self.cfg.respect_robots:
            return True
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(host)
        if cached is None or cached[0] < self._clock():
            parser: RobotFileParser | None
            try:
                r = self._raw_get(f"{host}/robots.txt", {})
                if r.status_code == 200:
                    parser = RobotFileParser(); parser.parse(r.text.splitlines())
                elif 400 <= r.status_code < 500:
                    parser = RobotFileParser(); parser.parse([])      # sem robots.txt => permitido
                else:
                    parser = None                                      # 5xx: não arrisca
            except httpx.HTTPError:
                parser = None
            cached = (self._clock() + self.cfg.robots_ttl_seconds, parser)
            self._robots[host] = cached
        parser = cached[1]
        return bool(parser and parser.can_fetch(self._ua_token, url))

    # -- GET --------------------------------------------------------------------
    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> HttpResult:
        if not self.allowed(url):
            raise CollectorError(f"robots.txt não permite (ou não pôde ser lido) para {url}", code="robotsDisallowed")
        cond = {}
        if etag:
            cond["If-None-Match"] = etag
        if last_modified:
            cond["If-Modified-Since"] = last_modified
        attempt = 0
        while True:
            try:
                r = self._raw_get(url, cond)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise CollectorError(f"HTTP {r.status_code} em {url}", retryable=True, code=f"http{r.status_code}")
            except httpx.HTTPError as e:
                err = CollectorError(f"falha de rede ({type(e).__name__}) em {url}", retryable=True, code="network")
            except CollectorError as e:
                err = e
            else:
                break
            if attempt >= self.max_retries:
                raise err
            self._sleep(2 ** attempt)
            attempt += 1
        if r.status_code == 304:
            return HttpResult(url, 304, not_modified=True, etag=etag, last_modified=last_modified)
        if r.status_code != 200:
            raise CollectorError(f"HTTP {r.status_code} em {url}", code=f"http{r.status_code}")
        return HttpResult(url, 200, r.content, r.headers.get("etag"), r.headers.get("last-modified"))
