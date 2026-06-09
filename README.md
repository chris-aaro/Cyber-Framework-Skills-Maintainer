# NIST Framework Claude Skills Maintainer

A **local-first, GitHub-based** system for maintaining framework-specific
[Claude Skills](https://docs.claude.com/) for three NIST frameworks, and for
**monitoring the official NIST sources** so those skills stay accurate over time.

Frameworks covered:

| Framework | Skill | Version (pinned) |
|---|---|---|
| NIST SP 800-53 | [`skills/nist-sp-800-53`](skills/nist-sp-800-53) | 5.1.1 |
| NIST Cybersecurity Framework 2.0 | [`skills/nist-csf-2.0`](skills/nist-csf-2.0) | 2.0 |
| NIST AI Risk Management Framework 1.0 | [`skills/nist-ai-rmf-1.0`](skills/nist-ai-rmf-1.0) | 1.0 |

## Design philosophy: source fidelity

These skills are deliberately **thin on framework content**. They contain how
Claude should *reason* about each framework — not copies of the official control
catalog, CSF Core, or AI RMF text. Every skill enforces two rules:

1. **Never invent** framework requirements, control/subcategory IDs, mappings, or
   official language. Official text is *referenced* via each skill's
   `sources.yaml`, never reconstructed from memory.
2. **Always distinguish** official framework text (`[OFFICIAL]`) from
   `[INTERPRETATION]`, `[IMPLEMENTATION]` advice, and `[MAPPING RATIONALE]`.

The validator (below) enforces structure and flags over-claiming language such as
"NIST mandates" or "guarantees compliance".

## Repository layout

```
frameworks.yaml              # registry of the three frameworks (single source of truth)
requirements.txt             # PyYAML + pytest (everything else is stdlib)
pytest.ini
common/utils.py              # shared helpers: YAML/JSON IO, http_get, hashing
monitors/monitor.py          # fetch sources, classify changes, open issues
validation/validate_skills.py# structure + guardrail validation (CI gate)
skills/<framework>/
  SKILL.md                   # the Claude Skill (guardrails + workflows)
  framework_profile.yaml     # id/version/structure (must match registry)
  sources.yaml               # canonical + related sources to monitor
  source_state.json          # last-observed snapshot per source (no DB)
  changelog.md               # Keep-a-Changelog history
  tests/test_skill.py        # per-skill validation tests
.github/workflows/
  monitor.yml                # scheduled monitoring -> GitHub issues
  validate.yml               # push/PR -> validate skills
```

No database and no cloud infrastructure beyond GitHub Actions are required.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Validate skills

```bash
python validation/validate_skills.py            # human-readable, exits non-zero on failure
python validation/validate_skills.py --json      # machine-readable
python validation/validate_skills.py --framework nist-csf-2.0
python -m pytest skills -q                        # per-skill tests
```

The validator checks that each skill has all required files, that `SKILL.md` has
all required sections, that `framework_profile.yaml` matches the registry id and
version, that `changelog.md` is non-empty, that `sources.yaml` has at least one
canonical source, and that no risky/over-claiming language appears in `SKILL.md`
unless tagged `[JUSTIFIED: ...]` or shown inside a ```risky-language-reference```
example block.

### Monitor sources

```bash
# Safe local dry run (classifies only, never opens issues, never writes state):
python monitors/monitor.py --dry-run

# Establish/update local baseline state after a reviewed change:
python monitors/monitor.py --write --framework nist-ai-rmf-1.0
```

In GitHub Actions the monitor runs on a weekly schedule with `GITHUB_TOKEN` and
`GITHUB_REPOSITORY` set, and opens issues for review-worthy changes. It runs
**read-only against the repo** — it does not commit state to `main`.

## How change monitoring works

For each source in a skill's `sources.yaml`, the monitor records reachability,
HTTP status, a SHA-256 of the page/file, the page title, and any detected version
/ publication date (via the `expected_metadata` regex hints). It compares the new
observation to `source_state.json` and classifies the change as exactly one of:

| Classification | Opens issue? | Meaning |
|---|:--:|---|
| `no_change` | no | All tracked signals identical (or first-run baseline). |
| `cosmetic_page_change` | no | Body hash changed but title/version/date stable. |
| `source_unreachable` | yes | Fetch failed or non-2xx response. |
| `metadata_change` | yes | Title/date changed, version unchanged. |
| `related_resource_change` | yes | Change on a `related` (non-canonical) source. |
| `errata_or_patch` | yes | Patch-level version bump or "errata" detected. |
| `new_framework_version` | yes | Major/minor version increase. |
| `ambiguous_requires_review` | yes | Change detected but not confidently classified. |

## Maintenance flow (issue first, PR for changes)

1. The scheduled monitor detects a review-worthy change and **opens a GitHub
   issue** (deduplicated by title).
2. A maintainer (optionally with Claude) verifies the change against the official
   source.
3. Claude-authored updates are proposed via a **pull request** that edits the
   relevant `SKILL.md` / `framework_profile.yaml` / `changelog.md`, bumps
   `version` in `frameworks.yaml` if applicable, and updates `source_state.json`.
4. `validate.yml` must pass before merge. **Nothing is auto-pushed to `main`.**

## Adding a new framework

1. Add an entry to `frameworks.yaml` (`id`, `name`, `version`, paths).
2. Create `skills/<id>/` with the six required members (copy an existing skill as
   a template): `SKILL.md`, `framework_profile.yaml`, `sources.yaml`,
   `source_state.json`, `changelog.md`, `tests/test_skill.py`.
3. Run `python validation/validate_skills.py` and `python -m pytest skills -q`.

## Notes & limitations

- Version/date detection uses conservative regex heuristics; when uncertain the
  monitor prefers `ambiguous_requires_review` over guessing.
- Source URLs in `sources.yaml` are public official NIST pages; confirm the
  pinned `version` / `publication_date` against them before relying on them.
- The skills intentionally embed no official framework text.
