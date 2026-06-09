"""
common/utils.py

Shared, dependency-light helpers reused by both monitors/monitor.py and
validation/validate_skills.py. Only PyYAML is used beyond the standard library;
HTTP, hashing, and JSON all use stdlib.

All path handling is anchored to the repository root so that local runs and
GitHub Actions runs resolve files identically.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

# Repository root = parent of the directory containing this file (common/).
REPO_ROOT = Path(__file__).resolve().parent.parent

FRAMEWORKS_FILE = REPO_ROOT / "frameworks.yaml"

USER_AGENT = (
    "cyber-framework-skills-maintainer/0.1 (+https://github.com/) "
    "monitoring official cyber framework sources"
)


# --------------------------------------------------------------------------- #
# Filesystem / serialization helpers
# --------------------------------------------------------------------------- #
def resolve(path: str | Path) -> Path:
    """Resolve a repo-relative path to an absolute Path under REPO_ROOT."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def load_yaml(path: str | Path) -> Any:
    """Load a YAML file (safe loader). Raises FileNotFoundError if missing."""
    with open(resolve(path), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: str | Path) -> Any:
    with open(resolve(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: str | Path, obj: Any) -> None:
    """Write JSON with stable, diff-friendly formatting (trailing newline)."""
    with open(resolve(path), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def read_text(path: str | Path) -> str:
    with open(resolve(path), "r", encoding="utf-8") as fh:
        return fh.read()


def load_frameworks() -> list[dict]:
    """Return the list of framework registry entries from frameworks.yaml."""
    data = load_yaml(FRAMEWORKS_FILE)
    if not isinstance(data, dict) or "frameworks" not in data:
        raise ValueError("frameworks.yaml must contain a top-level 'frameworks' list")
    return data["frameworks"]


def find_framework(framework_id: str) -> Optional[dict]:
    for fw in load_frameworks():
        if fw.get("id") == framework_id:
            return fw
    return None


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# HTTP (stdlib urllib)
# --------------------------------------------------------------------------- #
@dataclass
class FetchResult:
    """Outcome of fetching a single source URL."""

    url: str
    reachable: bool
    http_status: Optional[int]
    body: Optional[str]
    content_type: Optional[str]
    error: Optional[str] = None

    @property
    def content_sha256(self) -> Optional[str]:
        if self.body is None:
            return None
        return sha256_text(self.body)


def http_get(url: str, timeout: int = 30) -> FetchResult:
    """
    Fetch a URL with the stdlib. Never raises for network/HTTP errors; instead
    returns a FetchResult with reachable=False so the monitor can classify the
    source as unreachable rather than crashing.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
            status = getattr(resp, "status", None) or resp.getcode()
            return FetchResult(
                url=url,
                reachable=200 <= int(status) < 300,
                http_status=int(status),
                body=body,
                content_type=resp.headers.get_content_type(),
            )
    except urllib.error.HTTPError as exc:
        return FetchResult(
            url=url,
            reachable=False,
            http_status=int(exc.code),
            body=None,
            content_type=None,
            error=f"HTTPError: {exc.code} {exc.reason}",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return FetchResult(
            url=url,
            reachable=False,
            http_status=None,
            body=None,
            content_type=None,
            error=f"{type(exc).__name__}: {exc}",
        )
