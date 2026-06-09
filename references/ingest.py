#!/usr/bin/env python3
"""
references/ingest.py

Download official machine-readable framework artifacts and transform them into
the split, diffable reference files each skill bundles (progressive disclosure).

This is the deterministic, cheap half of "point 2" — it does the heavy
downloading/parsing so the Claude Code routine doesn't burn tokens re-reading
hundreds of pages. The routine reviews the resulting diff and authors the prose
summary; this script just produces faithful structured data.

Driven by `structured_content` entries in each skill's sources.yaml:

    structured_content:
      - id: sp800-53-oscal-catalog
        url: "https://raw.githubusercontent.com/usnistgov/oscal-content/.../catalog.json"
        format: json
        transform: oscal_catalog_split   # must exist in references/transforms.py
        output_dir: references            # relative to the skill dir

Modes:
  (default)   download + transform + write reference files; rewrite index.json.
  --check     download + transform in memory and compare to what's on disk;
              exit non-zero if they differ (CI / drift guard). No writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.utils import (  # noqa: E402
    dump_json,
    http_get,
    load_frameworks,
    load_yaml,
    resolve,
)
from references.transforms import TRANSFORMS  # noqa: E402


def _structured_sources(framework: dict) -> list[dict]:
    doc = load_yaml(framework["sources"]) or {}
    return doc.get("structured_content") or []


def _render_files(framework: dict, source: dict) -> tuple[Path, dict, dict]:
    """Fetch + transform one structured source. Returns (out_dir, index, files)."""
    transform = TRANSFORMS.get(source.get("transform"))
    if transform is None:
        raise ValueError(
            f"unknown transform {source.get('transform')!r} for source "
            f"{source.get('id')!r}; add it to references/transforms.py"
        )
    fetch = http_get(source["url"], timeout=source.get("timeout", 60))
    if not fetch.reachable or not fetch.body:
        raise RuntimeError(
            f"could not fetch {source['id']} ({source['url']}): "
            f"{fetch.error or fetch.http_status}"
        )
    artifact = json.loads(fetch.body)
    index, files = transform(artifact, framework)

    out_dir = resolve(framework["skill_dir"]) / source.get("output_dir", "references")
    return out_dir, index, files


def _index_matches_registry(framework: dict, index: dict) -> Optional[str]:
    reg = str(framework.get("version", "")).strip()
    got = str(index.get("version", "")).strip()
    if reg and got and reg != got:
        return (
            f"detected catalog version {got!r} != pinned registry version {reg!r} "
            "(this is expected when a new version has shipped; bump the pin in a PR)"
        )
    return None


def ingest_framework(framework: dict, *, check: bool) -> int:
    sources = _structured_sources(framework)
    if not sources:
        print(f"  - {framework['id']}: no structured_content sources (skipped)")
        return 0

    drift = 0
    for source in sources:
        out_dir, index, files = _render_files(framework, source)

        # Normalize a volatile field so --check doesn't flag every run.
        compare_index = dict(index)
        compare_index.pop("generated_at", None)

        if check:
            differing = []
            on_disk_index = _load_if_exists(out_dir / "index.json")
            if on_disk_index is not None:
                on_disk_index.pop("generated_at", None)
            if on_disk_index != compare_index:
                differing.append("index.json")
            for rel, content in files.items():
                if _load_if_exists(out_dir / rel) != content:
                    differing.append(rel)
            if differing:
                drift += 1
                print(
                    f"  ! {framework['id']}/{source['id']}: {len(differing)} "
                    f"reference file(s) differ from source "
                    f"(e.g. {differing[0]})"
                )
            else:
                print(f"  ✓ {framework['id']}/{source['id']}: reference files current")
            continue

        # Write mode.
        for rel, content in files.items():
            dump_json(out_dir / rel, content)
        dump_json(out_dir / "index.json", index)
        note = _index_matches_registry(framework, index)
        print(
            f"  + {framework['id']}/{source['id']}: wrote {len(files)} file(s) + "
            f"index.json (version {index.get('version')}, "
            f"{index.get('control_count')} controls)"
        )
        if note:
            print(f"      note: {note}")
    return drift


def _load_if_exists(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest official structured framework content into skill references."
    )
    parser.add_argument("--framework", help="Only this framework id.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare freshly transformed content to what's on disk; "
        "exit non-zero on any difference. No writes.",
    )
    args = parser.parse_args(argv)

    total_drift = 0
    matched = False
    for fw in load_frameworks():
        if args.framework and fw.get("id") != args.framework:
            continue
        matched = True
        total_drift += ingest_framework(fw, check=args.check)

    if not matched:
        print("No frameworks matched.", file=sys.stderr)
        return 2
    if args.check and total_drift:
        print(f"\n{total_drift} source(s) out of date. Run ingest to refresh.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
