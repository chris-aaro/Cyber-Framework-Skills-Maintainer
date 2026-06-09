#!/usr/bin/env python3
"""
monitors/propose_update.py

Deterministic auto-update proposer. When the monitor's version-pin check finds
that the version pinned in this repository differs from the version detected on
the live canonical source, this script mechanically prepares a *proposed* update
so a maintainer only has to review and approve a pull request.

What it changes (deterministically — no invented content):
  * `frameworks.yaml`        -> bump the framework's `version`
  * `framework_profile.yaml` -> bump the top-level `version`
  * `source_state.json`      -> refresh the baseline from the live observation
  * `changelog.md`           -> prepend a dated entry under [Unreleased]

What it deliberately does NOT do:
  * It does not rewrite SKILL.md control language, requirements, or mappings.
  * It does not invent what changed substantively between versions.
  The opened PR explicitly asks the human reviewer to confirm against the
  official source before merging.

Exit code is always 0 (so CI can branch on the emitted output rather than on a
failure). When run inside GitHub Actions it writes `has_changes`, `framework`,
`old_version`, and `new_version` to $GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.utils import (  # noqa: E402
    dump_json,
    http_get,
    load_frameworks,
    load_yaml,
    read_text,
    resolve,
)
from monitors.monitor import (  # noqa: E402
    Observation,
    check_version_pin,
    observation_to_state,
    observe,
)


# --------------------------------------------------------------------------- #
# Deterministic, comment-preserving file edits
# --------------------------------------------------------------------------- #
def bump_version_in_frameworks_yaml(
    path: str | Path, framework_id: str, new_version: str
) -> bool:
    """
    Replace the `version:` line inside the block for `framework_id` only,
    preserving all comments and formatting. Returns True if a change was made.
    """
    p = resolve(path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    in_block = False
    changed = False
    id_re = re.compile(r"^\s*-\s+id:\s*['\"]?" + re.escape(framework_id) + r"['\"]?\s*$")
    new_item_re = re.compile(r"^\s*-\s+id:\s*")
    version_re = re.compile(r"^(\s*version:\s*)['\"]?[^'\"\n]+['\"]?(\s*)$")
    for i, line in enumerate(lines):
        if id_re.match(line):
            in_block = True
            continue
        if in_block and new_item_re.match(line):
            break  # reached the next framework without finding a version line
        if in_block:
            m = version_re.match(line)
            if m:
                lines[i] = f'{m.group(1)}"{new_version}"{m.group(2)}'
                changed = True
                break
    if changed:
        p.write_text("".join(lines), encoding="utf-8")
    return changed


def bump_version_in_profile(path: str | Path, new_version: str) -> bool:
    """Replace the top-level `version:` line in a framework_profile.yaml."""
    p = resolve(path)
    text = p.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r"(?m)^(version:\s*)['\"]?[^'\"\n]+['\"]?(\s*)$",
        lambda m: f'{m.group(1)}"{new_version}"{m.group(2)}',
        text,
        count=1,
    )
    if n:
        p.write_text(new_text, encoding="utf-8")
    return bool(n)


def prepend_changelog_entry(path: str | Path, entry_lines: list[str]) -> bool:
    """Insert an entry immediately after the `## [Unreleased]` heading."""
    p = resolve(path)
    text = p.read_text(encoding="utf-8")
    marker = "## [Unreleased]"
    idx = text.find(marker)
    if idx == -1:
        # No Unreleased section; prepend a fresh one after the first heading line.
        block = marker + "\n\n" + "\n".join(entry_lines) + "\n\n"
        p.write_text(block + text, encoding="utf-8")
        return True
    insert_at = text.find("\n", idx) + 1
    block = "\n" + "\n".join(entry_lines) + "\n"
    p.write_text(text[:insert_at] + block + text[insert_at:], encoding="utf-8")
    return True


def refresh_state_baseline(
    state_path: str | Path, observations: list[Observation]
) -> None:
    """Write observed source snapshots into source_state.json (new baseline)."""
    p = resolve(state_path)
    state = {"sources": {}}
    if p.is_file():
        try:
            import json

            state = json.loads(p.read_text(encoding="utf-8"))
            state.setdefault("sources", {})
        except Exception:  # noqa: BLE001
            state = {"sources": {}}
    for obs in observations:
        state["sources"][obs.source_id] = observation_to_state(obs)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    dump_json(p, state)


# --------------------------------------------------------------------------- #
# Detection (reuses the monitor's logic)
# --------------------------------------------------------------------------- #
def gather_observations(framework: dict, timeout: int) -> list[Observation]:
    sources_doc = load_yaml(framework["sources"]) or {}
    sources = []
    for s in sources_doc.get("canonical_sources") or []:
        s = dict(s)
        s.setdefault("type", "canonical")
        sources.append(s)
    for s in sources_doc.get("related_sources") or []:
        s = dict(s)
        s.setdefault("type", "related")
        sources.append(s)
    observations = []
    for source in sources:
        fetch = http_get(source["url"], timeout=timeout)
        observations.append(observe(source, fetch))
    return observations


def propose_for_framework(
    framework: dict, *, apply: bool, timeout: int
) -> Optional[dict]:
    """
    Detect a version-pin mismatch and (optionally) apply the deterministic edits.
    Returns a result dict if a mismatch was found, else None.
    """
    observations = gather_observations(framework, timeout)
    mismatch = check_version_pin(framework, observations)
    if not mismatch:
        print(f"  ✓ {framework['id']}: version pin OK (no proposal needed)")
        return None

    old = mismatch["pinned"]
    new = mismatch["detected"]
    print(
        f"  ! {framework['id']}: pinned {old} -> detected {new} "
        f"({mismatch['classification']})"
    )

    if not apply:
        print("    (dry-run: no files changed; pass --apply to edit)")
        return mismatch

    today = datetime.now(timezone.utc).date().isoformat()
    source_urls = [
        obs.url for obs in observations
        if obs.source_id in mismatch["source_ids"]
    ]
    changelog_entry = [
        "### Changed",
        f"- Pinned version updated from `{old}` to `{new}` to match the version "
        f"detected on the canonical source(s) on {today}: "
        + ", ".join(source_urls) + ".",
        f"  Detected change class: `{mismatch['classification']}`. "
        "Reviewer: confirm against the official source and update SKILL.md if the "
        "substantive framework content changed.",
    ]

    c1 = bump_version_in_frameworks_yaml("frameworks.yaml", framework["id"], new)
    c2 = bump_version_in_profile(framework["profile"], new)
    prepend_changelog_entry(framework["skill_dir"] + "/changelog.md", changelog_entry)
    refresh_state_baseline(framework["state"], observations)

    if not (c1 and c2):
        print(
            f"    ! warning: version line not found in "
            f"{'frameworks.yaml' if not c1 else ''} "
            f"{'profile' if not c2 else ''}".rstrip()
        )
    print(f"    edited: frameworks.yaml, {framework['profile']}, changelog.md, state")
    mismatch["old_version"] = old
    mismatch["new_version"] = new
    return mismatch


def _write_github_output(result: Optional[dict], framework_id: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    has = bool(result)
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"has_changes={'true' if has else 'false'}\n")
        if has:
            fh.write(f"framework={framework_id}\n")
            fh.write(f"old_version={result.get('old_version', result.get('pinned',''))}\n")
            fh.write(f"new_version={result.get('new_version', result.get('detected',''))}\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Propose deterministic version-bump updates as a PR-ready diff."
    )
    parser.add_argument(
        "--framework", required=True, help="Framework id to check/propose for."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually edit files (default is a dry-run that only reports).",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    args = parser.parse_args(argv)

    framework = next(
        (fw for fw in load_frameworks() if fw.get("id") == args.framework), None
    )
    if not framework:
        print(f"Unknown framework id: {args.framework}", file=sys.stderr)
        return 2

    result = propose_for_framework(framework, apply=args.apply, timeout=args.timeout)
    _write_github_output(result if args.apply else None, args.framework)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
