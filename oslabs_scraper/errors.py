"""Exceptions used across the scraper."""

from __future__ import annotations


class ScrapeError(Exception):
    """Base class for every error the scraper raises on purpose."""


class FetchError(ScrapeError):
    """A single URL could not be retrieved."""

    def __init__(self, url: str, status: int | None = None, message: str = "") -> None:
        self.url = url
        self.status = status
        detail = message or (f"HTTP {status}" if status else "request failed")
        super().__init__(f"{detail} -> {url}")


class RobotsDisallowed(ScrapeError):
    """robots.txt forbids fetching the URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"robots.txt disallows {url}")


class UnsafePathError(ScrapeError):
    """A URL would be written outside of the output directory."""

    def __init__(self, url: str, path: str) -> None:
        self.url = url
        self.path = path
        super().__init__(f"refusing to write {path!r} for {url}")


class ConfigError(ScrapeError):
    """Invalid configuration or command line combination."""
