#!/usr/bin/env python3
"""
monitors/monitor.py

Monitor official cyber framework sources for changes and (in CI) open a GitHub
issue when a change may require human + Claude review.

Design constraints honored here:
  * Standard library only, plus PyYAML (via common.utils).
  * No database; state lives in each skill's source_state.json.
  * No auto-push to main. CI runs read-only against the repo and create issues.
    State files are only updated locally when run with --write.
  * A detected change creates an ISSUE first; skill edits happen later via PR.

Change classification (exactly these eight classes):
    no_change, source_unreachable, cosmetic_page_change, metadata_change,
    related_resource_change, errata_or_patch, new_framework_version,
    ambiguous_requires_review

Only review-worthy classes create issues (see REVIEW_WORTHY).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.utils import (  # noqa: E402
    USER_AGENT,
    FetchResult,
    http_get,
    load_frameworks,
    load_yaml,
    dump_json,
    load_json,
    resolve,
)

# --------------------------------------------------------------------------- #
# Classification constants
# --------------------------------------------------------------------------- #
NO_CHANGE = "no_change"
SOURCE_UNREACHABLE = "source_unreachable"
COSMETIC_PAGE_CHANGE = "cosmetic_page_change"
METADATA_CHANGE = "metadata_change"
RELATED_RESOURCE_CHANGE = "related_resource_change"
ERRATA_OR_PATCH = "errata_or_patch"
NEW_FRAMEWORK_VERSION = "new_framework_version"
AMBIGUOUS_REQUIRES_REVIEW = "ambiguous_requires_review"

# Classes that warrant a GitHub issue.
REVIEW_WORTHY = {
    SOURCE_UNREACHABLE,
    METADATA_CHANGE,
    RELATED_RESOURCE_CHANGE,
    ERRATA_OR_PATCH,
    NEW_FRAMEWORK_VERSION,
    AMBIGUOUS_REQUIRES_REVIEW,
}


# --------------------------------------------------------------------------- #
# Metadata extraction
# --------------------------------------------------------------------------- #
def extract_title(body: Optional[str]) -> Optional[str]:
    if not body:
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def extract_with_pattern(body: Optional[str], pattern: Optional[str]) -> Optional[str]:
    """Apply a regex from sources.yaml. Returns group(1) if present, else group(0)."""
    if not body or not pattern:
        return None
    try:
        m = re.search(pattern, body, re.IGNORECASE)
    except re.error:
        return None
    if not m:
        return None
    return (m.group(1) if m.groups() else m.group(0)).strip()


@dataclass
class Observation:
    """What we observed for a single source on this run."""

    source_id: str
    url: str
    type: str  # canonical | related
    reachable: bool
    http_status: Optional[int]
    content_sha256: Optional[str]
    title: Optional[str]
    detected_version: Optional[str]
    detected_pub_date: Optional[str]
    error: Optional[str] = None
    last_checked: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def observe(source: dict, fetch: FetchResult) -> Observation:
    meta = source.get("expected_metadata") or {}
    body = fetch.body
    title = extract_title(body)
    version = extract_with_pattern(body, meta.get("version_pattern"))
    if version and meta.get("version_normalize") == "underscore_to_dot":
        version = version.replace("_", ".")
    pub_date = extract_with_pattern(body, meta.get("date_pattern"))
    return Observation(
        source_id=source["id"],
        url=source["url"],
        type=source.get("type", "canonical"),
        reachable=fetch.reachable,
        http_status=fetch.http_status,
        content_sha256=fetch.content_sha256,
        title=title,
        detected_version=version,
        detected_pub_date=pub_date,
        error=fetch.error,
    )


# --------------------------------------------------------------------------- #
# Version comparison
# --------------------------------------------------------------------------- #
def _parse_version(v: Optional[str]) -> Optional[tuple[int, ...]]:
    if not v:
        return None
    nums = re.findall(r"\d+", v)
    if not nums:
        return None
    return tuple(int(n) for n in nums)


def classify_version_change(old: Optional[str], new: Optional[str]) -> Optional[str]:
    """
    Compare two version strings. Returns a classification or None if no
    meaningful version change can be determined.
    """
    if old is None or new is None or old == new:
        return None
    po, pn = _parse_version(old), _parse_version(new)
    if po is None or pn is None:
        return AMBIGUOUS_REQUIRES_REVIEW
    # Pad to equal length for comparison.
    length = max(len(po), len(pn))
    po += (0,) * (length - len(po))
    pn += (0,) * (length - len(pn))
    if pn[:2] > po[:2] or pn[0] > po[0]:
        return NEW_FRAMEWORK_VERSION
    # Major.minor unchanged but a later position bumped -> patch/errata.
    if pn > po:
        return ERRATA_OR_PATCH
    # Version went backwards or otherwise odd.
    return AMBIGUOUS_REQUIRES_REVIEW


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(prev: Optional[dict], obs: Observation) -> str:
    """Classify the change between prior state (prev) and this observation."""
    if not obs.reachable:
        return SOURCE_UNREACHABLE

    # First-ever observation (no baseline): establish baseline, not a change.
    if not prev or prev.get("content_sha256") is None:
        return NO_CHANGE

    hash_changed = obs.content_sha256 != prev.get("content_sha256")
    title_changed = (obs.title or None) != (prev.get("title") or None)
    date_changed = (obs.detected_pub_date or None) != (prev.get("detected_pub_date") or None)
    version_change = classify_version_change(
        prev.get("detected_version"), obs.detected_version
    )

    if not hash_changed and not title_changed and not date_changed and not version_change:
        return NO_CHANGE

    # Version-driven classifications take precedence (most consequential).
    if version_change in (NEW_FRAMEWORK_VERSION, ERRATA_OR_PATCH):
        return version_change

    # "errata" keyword appearing in title is a strong patch signal.
    if obs.title and "errata" in obs.title.lower():
        return ERRATA_OR_PATCH

    # Changes on a related (non-canonical) resource.
    if obs.type == "related":
        return RELATED_RESOURCE_CHANGE

    # Metadata moved but version did not.
    if title_changed or date_changed:
        return METADATA_CHANGE

    # Only the body hash moved, metadata stable -> cosmetic.
    if hash_changed:
        return COSMETIC_PAGE_CHANGE

    return AMBIGUOUS_REQUIRES_REVIEW


# --------------------------------------------------------------------------- #
# GitHub issue creation (stdlib urllib + REST API)
# --------------------------------------------------------------------------- #
def _existing_issue_titles(repo: str, token: str) -> set[str]:
    """Fetch open issue titles to avoid creating duplicates."""
    url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=100"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {item.get("title", "") for item in data if "pull_request" not in item}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return set()


def create_github_issue(repo: str, token: str, title: str, body: str) -> bool:
    url = f"https://api.github.com/repos/{repo}/issues"
    payload = json.dumps(
        {"title": title, "body": body, "labels": ["source-change", "needs-review"]}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.getcode() < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"    ! failed to create issue: {exc}", file=sys.stderr)
        return False


def check_version_pin(
    framework: dict, observations: list[Observation]
) -> Optional[dict]:
    """
    Compare the detected version from canonical sources against the pinned
    version declared in frameworks.yaml. Returns a mismatch dict if they
    differ, None if they match or no version could be detected.

    This runs on every monitor execution regardless of whether the source
    hash changed — it validates that the skill stays current against the
    live source, not just that nothing changed since last run.
    """
    pinned = str(framework.get("version", "")).strip()
    if not pinned:
        return None

    # Collect detected versions from canonical sources only.
    detected_versions = [
        obs.detected_version
        for obs in observations
        if obs.type == "canonical" and obs.detected_version and obs.reachable
    ]
    if not detected_versions:
        return None

    # Use the first canonical source that detected a version (most authoritative).
    detected = detected_versions[0].strip()
    if not detected:
        return None

    version_classification = classify_version_change(pinned, detected)
    if version_classification is None:
        return None  # versions match or are indistinguishable

    return {
        "pinned": pinned,
        "detected": detected,
        "classification": version_classification,
        "source_ids": [
            obs.source_id
            for obs in observations
            if obs.type == "canonical" and obs.detected_version == detected
        ],
    }


def build_pin_mismatch_issue(framework: dict, mismatch: dict) -> tuple[str, str]:
    title = (
        f"[{framework['id']}] version_pin_mismatch: "
        f"pinned {mismatch['pinned']} but source detected {mismatch['detected']}"
    )
    lines = [
        "The monitor detected that the **pinned version in this repository differs "
        "from the version detected on the live official source**.",
        "",
        f"- **Framework:** {framework['name']} (`{framework['id']}`)",
        f"- **Pinned version** (`frameworks.yaml` + `framework_profile.yaml`): "
        f"`{mismatch['pinned']}`",
        f"- **Detected version** (live source): `{mismatch['detected']}`",
        f"- **Change classification:** `{mismatch['classification']}`",
        f"- **Source(s) where detected:** {', '.join(f'`{s}`' for s in mismatch['source_ids'])}",
        "",
        "## Next steps",
        "1. Visit the canonical source URL(s) above and confirm the detected version.",
        "2. Review what changed between the pinned and detected versions.",
        "3. Open a **pull request** that:",
        "   - Updates `version` in `frameworks.yaml` and `framework_profile.yaml`.",
        "   - Updates `SKILL.md` and `changelog.md` to reflect any content changes.",
        "   - Updates `source_state.json` with the new baseline.",
        "",
        "_Do not update the pinned version without verifying the change against the "
        "official source. Distinguish official framework text from interpretation._",
    ]
    return title, "\n".join(lines)


def build_issue(framework: dict, obs: Observation, classification: str) -> tuple[str, str]:
    title = f"[{framework['id']}] {classification}: {obs.source_id}"
    lines = [
        f"Automated monitor detected a change that may require review.",
        "",
        f"- **Framework:** {framework['name']} (`{framework['id']}`)",
        f"- **Source:** `{obs.source_id}` ({obs.type})",
        f"- **URL:** {obs.url}",
        f"- **Classification:** `{classification}`",
        f"- **Reachable:** {obs.reachable} (HTTP {obs.http_status})",
        f"- **Detected title:** {obs.title!r}",
        f"- **Detected version:** {obs.detected_version!r}",
        f"- **Detected publication date:** {obs.detected_pub_date!r}",
        f"- **Checked at:** {obs.last_checked}",
    ]
    if obs.error:
        lines.append(f"- **Error:** {obs.error}")
    lines += [
        "",
        "## Next steps",
        "1. Verify the change against the official source above.",
        "2. If the framework content genuinely changed, open a **pull request** "
        "updating the relevant skill (SKILL.md, framework_profile.yaml, changelog.md) "
        "and the `version` in `frameworks.yaml` if applicable.",
        "3. Update `source_state.json` **in that PR** so main stays authoritative.",
        "",
        "_Do not edit framework requirements or control language without confirming "
        "against the official source. Distinguish official text from interpretation._",
    ]
    return title, "\n".join(lines)


# --------------------------------------------------------------------------- #
# State handling
# --------------------------------------------------------------------------- #
def load_state(state_path: str | Path) -> dict:
    p = resolve(state_path)
    if not p.is_file():
        return {"sources": {}}
    try:
        data = load_json(p)
    except Exception:  # noqa: BLE001
        return {"sources": {}}
    if "sources" not in data:
        data["sources"] = {}
    return data


def observation_to_state(obs: Observation) -> dict:
    d = asdict(obs)
    d.pop("source_id", None)
    return d


# --------------------------------------------------------------------------- #
# Main monitoring loop
# --------------------------------------------------------------------------- #
def monitor_framework(
    framework: dict,
    *,
    write: bool,
    repo: Optional[str],
    token: Optional[str],
    timeout: int,
) -> list[dict]:
    """Monitor one framework's sources. Returns a list of per-source result dicts."""
    sources_doc = load_yaml(framework["sources"]) or {}
    canonical = sources_doc.get("canonical_sources") or []
    related = sources_doc.get("related_sources") or []
    all_sources = []
    for s in canonical:
        s = dict(s)
        s.setdefault("type", "canonical")
        all_sources.append(s)
    for s in related:
        s = dict(s)
        s.setdefault("type", "related")
        all_sources.append(s)

    state = load_state(framework["state"])
    existing_titles = (
        _existing_issue_titles(repo, token) if (repo and token) else set()
    )

    results = []
    all_observations: list[Observation] = []
    print(f"== {framework['id']} ({len(all_sources)} sources) ==")
    for source in all_sources:
        fetch = http_get(source["url"], timeout=timeout)
        obs = observe(source, fetch)
        all_observations.append(obs)
        prev = state["sources"].get(source["id"])
        classification = classify(prev, obs)
        review = classification in REVIEW_WORTHY

        print(f"  - {source['id']:<28} {classification}")

        issue_created = False
        if review and repo and token:
            title, body = build_issue(framework, obs, classification)
            if title in existing_titles:
                print(f"      (issue already open: {title!r})")
            else:
                issue_created = create_github_issue(repo, token, title, body)
                if issue_created:
                    existing_titles.add(title)
                    print(f"      + opened issue: {title!r}")

        # Update in-memory state snapshot (persisted only if --write).
        state["sources"][source["id"]] = observation_to_state(obs)

        results.append(
            {
                "framework_id": framework["id"],
                "source_id": source["id"],
                "classification": classification,
                "review_worthy": review,
                "issue_created": issue_created,
            }
        )

    # ------------------------------------------------------------------ #
    # Version pin check — runs every time regardless of hash changes.
    # ------------------------------------------------------------------ #
    observations = all_observations
    mismatch = check_version_pin(framework, observations)
    pin_issue_created = False
    if mismatch:
        label = (
            f"  ! version_pin_mismatch  pinned={mismatch['pinned']}  "
            f"detected={mismatch['detected']}  ({mismatch['classification']})"
        )
        print(label)
        if repo and token:
            pin_title, pin_body = build_pin_mismatch_issue(framework, mismatch)
            if pin_title in existing_titles:
                print(f"      (issue already open: {pin_title!r})")
            else:
                pin_issue_created = create_github_issue(repo, token, pin_title, pin_body)
                if pin_issue_created:
                    existing_titles.add(pin_title)
                    print(f"      + opened issue: {pin_title!r}")
        results.append(
            {
                "framework_id": framework["id"],
                "source_id": "version_pin_check",
                "classification": f"version_pin_mismatch:{mismatch['classification']}",
                "review_worthy": True,
                "issue_created": pin_issue_created,
            }
        )
    else:
        print(f"  ✓ version pin OK  (pinned={framework.get('version')})")

    if write:
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        dump_json(framework["state"], state)
        print(f"  state written -> {framework['state']}")

    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor cyber framework sources.")
    parser.add_argument("--framework", help="Monitor only this framework id.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist observed state to source_state.json (local use only; "
        "CI must not commit state to main).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Never create issues; just classify and print. Default when no "
        "GITHUB_TOKEN/GITHUB_REPOSITORY are set.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    parser.add_argument("--report", help="Write a JSON run report to this path.")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")  # "owner/name"
    if args.dry_run or not (token and repo):
        if not args.dry_run:
            print("No GITHUB_TOKEN/GITHUB_REPOSITORY found -> dry-run (no issues).")
        token = repo = None

    all_results = []
    for fw in load_frameworks():
        if args.framework and fw.get("id") != args.framework:
            continue
        all_results.extend(
            monitor_framework(
                fw, write=args.write, repo=repo, token=token, timeout=args.timeout
            )
        )

    review = sum(1 for r in all_results if r["review_worthy"])
    created = sum(1 for r in all_results if r["issue_created"])
    print(
        f"\nChecked {len(all_results)} sources | "
        f"{review} review-worthy | {created} issue(s) created."
    )

    if args.report:
        dump_json(args.report, {"results": all_results})
        print(f"report written -> {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
