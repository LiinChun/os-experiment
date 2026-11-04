"""A small, polite HTTP client.

Features the scraper relies on:

* connection pooling and retries with exponential backoff (via urllib3),
* a minimum delay between requests (``--delay``),
* ``robots.txt`` awareness (the site currently has none - 404 means "allow"),
* conditional requests (``If-None-Match`` / ``If-Modified-Since``) so repeated
  runs only re-download what actually changed,
* a hard size cap per response so a runaway mirror cannot fill the disk.
"""

from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import FetchError, RobotsDisallowed
from .util import is_http_url, origin_of, site_root

DEFAULT_USER_AGENT = (
    "oslabs-scraper/1.0 (+https://github.com/LiinChun/os-experiment; "
    "course-material mirror)"
)


@dataclass(frozen=True)
class FetchResult:
    """Outcome of one HTTP request."""

    url: str
    status: int
    content: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    not_modified: bool = False
    final_url: str = ""

    @property
    def content_type(self) -> str:
        """Lower-case MIME type without parameters (``text/html``)."""
        return self.headers.get("Content-Type", "").split(";")[0].strip().lower()

    @property
    def charset(self) -> str:
        params = self.headers.get("Content-Type", "")
        for part in params.split(";")[1:]:
            key, _, value = part.partition("=")
            if key.strip().lower() == "charset":
                return value.strip().strip('"')
        return ""

    @property
    def etag(self) -> str:
        return self.headers.get("ETag", "")

    @property
    def last_modified(self) -> str:
        return self.headers.get("Last-Modified", "")

    def text(self) -> str:
        encoding = self.charset or "utf-8"
        try:
            return self.content.decode(encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class Fetcher:
    """Throttled, retrying HTTP client scoped to one site."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        retries: int = 3,
        delay: float = 0.3,
        verify: bool = True,
        max_bytes: int = 8 * 1024 * 1024,
        respect_robots: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self.verify = verify
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots

        self._session = requests.Session()
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            }
        )

        self._robot_parsers: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._next_request_at = 0.0
        self.request_count = 0

    # -- lifecycle --------------------------------------------------------- #
    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- throttling -------------------------------------------------------- #
    def _throttle(self) -> None:
        if self.delay:
            now = time.monotonic()
            if now < self._next_request_at:
                time.sleep(self._next_request_at - now)
            self._next_request_at = time.monotonic() + self.delay
        self.request_count += 1

    # -- robots.txt -------------------------------------------------------- #
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        origin = origin_of(url)
        if origin in self._robot_parsers:
            return self._robot_parsers[origin]

        parser = urllib.robotparser.RobotFileParser()
        robots_url = site_root(url) + "robots.txt"
        try:
            # ``check_robots=False`` avoids recursing back into this method.
            result = self.get(robots_url, check_robots=False)
        except FetchError:
            # 404 or unreachable robots.txt is treated as "everything allowed".
            self._robot_parsers[origin] = None  # type: ignore[assignment]
            return None
        parser.parse(result.text().splitlines())
        self._robot_parsers[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        """Return ``False`` when robots.txt disallows *url*."""
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    # -- requests ---------------------------------------------------------- #
    def get(
        self,
        url: str,
        *,
        etag: str = "",
        last_modified: str = "",
        allow_status: tuple[int, ...] = (),
        check_robots: bool = True,
    ) -> FetchResult:
        """GET *url* and return the response body as bytes.

        Raises :class:`FetchError` for network errors and non-2xx statuses
        (except ``304`` and anything listed in *allow_status*), and
        :class:`RobotsDisallowed` when robots.txt forbids the request.
        """
        if not is_http_url(url):
            raise FetchError(url, message="not an http(s) URL")
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        self._throttle()
        try:
            response = self._session.get(
                url,
                timeout=self.timeout,
                verify=self.verify,
                headers=headers,
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:
            raise FetchError(url, message=f"{type(exc).__name__}: {exc}") from exc

        with response:
            if response.status_code == 304:
                return FetchResult(
                    url=url,
                    status=304,
                    headers=dict(response.headers),
                    not_modified=True,
                    final_url=response.url,
                )
            if response.status_code >= 400 and response.status_code not in allow_status:
                raise FetchError(url, status=response.status_code)

            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                raise FetchError(
                    url,
                    message=f"response of {declared} bytes exceeds --max-asset-bytes",
                )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_bytes:
                    raise FetchError(
                        url,
                        message=f"response exceeds --max-asset-bytes ({self.max_bytes})",
                    )
                chunks.append(chunk)

            return FetchResult(
                url=url,
                status=response.status_code,
                content=b"".join(chunks),
                headers=dict(response.headers),
                final_url=response.url,
            )
