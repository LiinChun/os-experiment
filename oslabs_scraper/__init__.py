"""oslabs-scraper - mirror ``https://os-labs.p.cs-lab.top`` into a git repository.

The package is deliberately small and dependency-light (``requests`` only):

``htmltree``   a tolerant HTML parser that builds a tiny DOM
``discover``   navigation / link discovery
``fetcher``     polite HTTP client (retries, throttling, robots.txt, 304s)
``assets``     extraction of images / stylesheets / downloadable files
``mirror``     the end-to-end "fetch and snapshot" orchestration
``manifest``   hash based state file used for incremental scraping
``publish``    ``git add`` / ``commit`` / ``push`` helper
``cli``        command line entry point
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
