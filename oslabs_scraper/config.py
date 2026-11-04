"""Configuration object shared by the CLI and the mirror engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .util import normalize_url, site_root

DEFAULT_BASE_URL = "https://os-labs.p.cs-lab.top/"


@dataclass
class Config:
    """Everything that influences a scrape run."""

    base_url: str = DEFAULT_BASE_URL
    out_dir: Path = Path("raw")
    index_path: Path | None = Path("INDEX.md")
    user_agent: str = ""
    delay: float = 0.3
    timeout: float = 30.0
    retries: int = 3
    verify_tls: bool = True
    max_bytes: int = 8 * 1024 * 1024
    max_pages: int = 500
    respect_robots: bool = True
    include_external: bool = False
    skip_patterns: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.base_url = site_root(normalize_url(self.base_url))
        self.out_dir = Path(self.out_dir)
        if self.delay < 0:
            raise ConfigError("--delay must be zero or positive")
        if self.timeout <= 0:
            raise ConfigError("--timeout must be positive")
        if self.max_pages <= 0:
            raise ConfigError("--max-pages must be positive")
        if self.max_bytes <= 0:
            raise ConfigError("--max-asset-bytes must be positive")

    @property
    def manifest_path(self) -> Path:
        """State file location: inside the mirror so it travels with the data."""
        return self.out_dir / "manifest.json"

    @property
    def start_url(self) -> str:
        """The crawl seed: the site root in its canonical ``index.html`` form."""
        return normalize_url(self.base_url)

    def is_skipped(self, url: str) -> bool:
        return any(part and part in url for part in self.skip_patterns)
