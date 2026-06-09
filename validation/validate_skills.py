#!/usr/bin/env python3
"""
validation/validate_skills.py

Structural and source-fidelity validation for the framework skills.

For each framework registered in frameworks.yaml this checks:
  1. All required skill files / directories exist.
  2. SKILL.md contains every required section heading.
  3. framework_profile.yaml framework_id and version match the registry.
  4. changelog.md exists and is non-empty.
  5. sources.yaml declares at least one canonical source.
  6. SKILL.md does not contain risky/over-claiming language unless it is
     either (a) inside the ```risky-language-reference``` fenced block, or
     (b) on a line carrying a `[JUSTIFIED: ...]` token.

Importable: tests import `validate_framework` / `validate_all`. Runnable: as a
script it prints a report and exits non-zero on any failure (CI gate).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Allow running as a script (python validation/validate_skills.py) and as a
# module import (from tests) without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.utils import (  # noqa: E402
    REPO_ROOT,
    load_frameworks,
    load_yaml,
    read_text,
    resolve,
)

# Files/directories every skill must contain.
REQUIRED_FILES = [
    "SKILL.md",
    "framework_profile.yaml",
    "sources.yaml",
    "source_state.json",
    "changelog.md",
]
REQUIRED_DIRS = ["tests"]

# Section headings every SKILL.md must contain (matched as markdown H2).
REQUIRED_SECTIONS = [
    "Purpose",
    "Scope",
    "Operating Principles",
    "Official vs. Interpretation",
    "Source Fidelity Guardrails",
    "Framework-Specific Workflows",
    "Limitations",
    "Sources",
]

# Additionally required only for skills that bundle structured content
# (content_mode: structured) — enforced in _check_reference_content.
STRUCTURED_REQUIRED_SECTIONS = ["Reference Data"]

# Risky / over-claiming phrases (case-insensitive).
RISKY_PHRASES = [
    "always required",
    "nist mandates",
    "guarantees compliance",
    "official mapping",
]

# A line is exempt from the risky-language scan if it carries this token.
JUSTIFICATION_TOKEN = "[JUSTIFIED:"

# Fenced block whose contents are exempt (lets a skill name the phrases as
# examples of what to avoid).
REFERENCE_FENCE = "risky-language-reference"


@dataclass
class FrameworkResult:
    framework_id: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #
def _check_required_files(skill_dir: Path, res: FrameworkResult) -> None:
    for rel in REQUIRED_FILES:
        p = skill_dir / rel
        if not p.is_file():
            res.errors.append(f"missing required file: {p.relative_to(REPO_ROOT)}")
    for rel in REQUIRED_DIRS:
        p = skill_dir / rel
        if not p.is_dir():
            res.errors.append(f"missing required directory: {p.relative_to(REPO_ROOT)}")


def _strip_reference_blocks(text: str) -> str:
    """Remove fenced ```risky-language-reference ... ``` blocks from text."""
    pattern = re.compile(
        r"^```+\s*" + re.escape(REFERENCE_FENCE) + r"\b.*?^```+\s*$",
        re.DOTALL | re.MULTILINE,
    )
    return pattern.sub("", text)


def _skill_headings(skill_dir: Path) -> set[str]:
    """Set of normalized markdown H2 headings in SKILL.md (lowercased, no trailing '.')."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return set()
    text = read_text(skill_md)
    return {
        m.group(1).strip().rstrip(".").lower()
        for m in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    }


def _check_skill_sections(skill_dir: Path, res: FrameworkResult) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return  # already reported by file check
    headings = _skill_headings(skill_dir)
    for section in REQUIRED_SECTIONS:
        if section.rstrip(".").lower() not in headings:
            res.errors.append(f"SKILL.md missing required section: '## {section}'")


def _check_profile(skill_dir: Path, fw: dict, res: FrameworkResult) -> None:
    profile_path = skill_dir / "framework_profile.yaml"
    if not profile_path.is_file():
        return
    try:
        profile = load_yaml(profile_path)
    except Exception as exc:  # noqa: BLE001
        res.errors.append(f"framework_profile.yaml could not be parsed: {exc}")
        return
    if not isinstance(profile, dict):
        res.errors.append("framework_profile.yaml must be a mapping")
        return
    if str(profile.get("framework_id")) != str(fw["id"]):
        res.errors.append(
            "framework_profile.yaml framework_id "
            f"'{profile.get('framework_id')}' != registry id '{fw['id']}'"
        )
    if str(profile.get("version")) != str(fw["version"]):
        res.errors.append(
            "framework_profile.yaml version "
            f"'{profile.get('version')}' != registry version '{fw['version']}'"
        )


def _check_changelog(skill_dir: Path, res: FrameworkResult) -> None:
    changelog = skill_dir / "changelog.md"
    if not changelog.is_file():
        return
    if not read_text(changelog).strip():
        res.errors.append("changelog.md exists but is empty")


def _check_sources(skill_dir: Path, res: FrameworkResult) -> None:
    sources_path = skill_dir / "sources.yaml"
    if not sources_path.is_file():
        return
    try:
        sources = load_yaml(sources_path)
    except Exception as exc:  # noqa: BLE001
        res.errors.append(f"sources.yaml could not be parsed: {exc}")
        return
    canonical = (sources or {}).get("canonical_sources") or []
    if not isinstance(canonical, list) or len(canonical) < 1:
        res.errors.append("sources.yaml must declare at least one canonical source")


def _check_reference_content(skill_dir: Path, fw: dict, res: FrameworkResult) -> None:
    """
    For skills with content_mode: structured, confirm the reference index exists,
    its version matches the registry, and every file it lists is present and
    non-empty. Skills without structured content are skipped.
    """
    profile_path = skill_dir / "framework_profile.yaml"
    if not profile_path.is_file():
        return
    try:
        profile = load_yaml(profile_path) or {}
    except Exception:  # noqa: BLE001
        return  # parse error already reported by _check_profile
    if profile.get("content_mode") != "structured":
        return

    # Structured skills must document how to use the bundled references.
    headings = _skill_headings(skill_dir)
    for section in STRUCTURED_REQUIRED_SECTIONS:
        if section.rstrip(".").lower() not in headings:
            res.errors.append(
                f"SKILL.md missing required section for structured content: "
                f"'## {section}'"
            )

    rel_index = profile.get("reference_index")
    if not rel_index:
        res.errors.append(
            "framework_profile.yaml content_mode is 'structured' but no "
            "reference_index is declared"
        )
        return
    index_path = skill_dir / rel_index
    if not index_path.is_file():
        res.errors.append(f"reference index not found: {rel_index} (run references/ingest.py)")
        return
    try:
        import json

        index = json.loads(read_text(index_path))
    except Exception as exc:  # noqa: BLE001
        res.errors.append(f"reference index could not be parsed: {exc}")
        return

    reg_version = str(fw.get("version", "")).strip()
    idx_version = str(index.get("version", "")).strip()
    if reg_version and idx_version and reg_version != idx_version:
        res.errors.append(
            f"reference index version '{idx_version}' != registry version "
            f"'{reg_version}' (re-run references/ingest.py and bump together)"
        )

    families = index.get("families") or []
    if not families:
        res.errors.append("reference index lists no families")
    index_dir = index_path.parent
    for fam in families:
        fpath = index_dir / fam.get("file", "")
        if not fpath.is_file() or not fpath.read_text(encoding="utf-8").strip():
            res.errors.append(
                f"reference file missing or empty: {fam.get('file')!r} "
                f"(family {fam.get('id')!r})"
            )


def _check_risky_language(skill_dir: Path, res: FrameworkResult) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return
    text = _strip_reference_blocks(read_text(skill_md))
    for lineno, line in enumerate(text.splitlines(), start=1):
        if JUSTIFICATION_TOKEN.lower() in line.lower():
            continue
        low = line.lower()
        for phrase in RISKY_PHRASES:
            if phrase in low:
                res.errors.append(
                    f"SKILL.md:{lineno} risky language '{phrase}' without "
                    f"[JUSTIFIED: ...] tag: {line.strip()[:80]!r}"
                )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def validate_framework(fw: dict) -> FrameworkResult:
    res = FrameworkResult(framework_id=fw.get("id", "<unknown>"))
    skill_dir = resolve(fw["skill_dir"])
    if not skill_dir.is_dir():
        res.errors.append(f"skill_dir does not exist: {fw['skill_dir']}")
        return res
    _check_required_files(skill_dir, res)
    _check_skill_sections(skill_dir, res)
    _check_profile(skill_dir, fw, res)
    _check_changelog(skill_dir, res)
    _check_sources(skill_dir, res)
    _check_reference_content(skill_dir, fw, res)
    _check_risky_language(skill_dir, res)
    return res


def validate_all(framework_id: Optional[str] = None) -> list[FrameworkResult]:
    results = []
    for fw in load_frameworks():
        if framework_id and fw.get("id") != framework_id:
            continue
        results.append(validate_framework(fw))
    return results


def _print_report(results: list[FrameworkResult]) -> None:
    for res in results:
        status = "PASS" if res.ok else "FAIL"
        print(f"[{status}] {res.framework_id}")
        for err in res.errors:
            print(f"    ERROR: {err}")
        for warn in res.warnings:
            print(f"    WARN:  {warn}")
    total = len(results)
    failed = sum(1 for r in results if not r.ok)
    print(f"\n{total - failed}/{total} skills passed validation.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate framework skills.")
    parser.add_argument("--framework", help="Validate only this framework id.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    results = validate_all(args.framework)
    if not results:
        print("No frameworks matched.", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "framework_id": r.framework_id,
                        "ok": r.ok,
                        "errors": r.errors,
                        "warnings": r.warnings,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
    else:
        _print_report(results)

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
