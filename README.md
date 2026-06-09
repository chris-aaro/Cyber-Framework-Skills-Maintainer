# Cyber Framework Claude Skills Maintainer

A **local-first, GitHub-based** system for maintaining framework-specific
[Claude Skills](https://docs.claude.com/) for cybersecurity and AI risk
frameworks, and for **monitoring the official sources** of those frameworks so
skills stay accurate over time.

Frameworks are registered in [`frameworks.yaml`](frameworks.yaml). The three
initial frameworks are:

| Framework | Skill | Version (pinned) |
|---|---|---|
| NIST SP 800-53 | [`skills/nist-sp-800-53`](skills/nist-sp-800-53) | 5.1.1 |
| NIST Cybersecurity Framework 2.0 | [`skills/nist-csf-2.0`](skills/nist-csf-2.0) | 2.0 |
| NIST AI Risk Management Framework 1.0 | [`skills/nist-ai-rmf-1.0`](skills/nist-ai-rmf-1.0) | 1.0 |

New frameworks can be added at any time by following the steps in
[Adding a new framework](#adding-a-new-framework).

## Design philosophy: source fidelity

These skills are deliberately **thin on framework content**. They contain how
Claude should *reason* about each framework — not copies of official control
catalogs, cores, or normative text. Every skill enforces two rules:

1. **Never invent** framework requirements, control/subcategory IDs, mappings, or
   official language. Official text is *referenced* via each skill's
   `sources.yaml`, never reconstructed from memory.
2. **Always distinguish** official framework text (`[OFFICIAL]`) from
   `[INTERPRETATION]`, `[IMPLEMENTATION]` advice, and `[MAPPING RATIONALE]`.

The validator enforces structure and flags over-claiming language such as
"NIST mandates" or "guarantees compliance".

## Repository layout

```
frameworks.yaml              # registry of all frameworks (single source of truth)
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

The validator checks that each skill has all required files, that `SKILL.md`
has all required sections, that `framework_profile.yaml` matches the registry
id and version, that `changelog.md` is non-empty, that `sources.yaml` has at
least one canonical source, and that no risky/over-claiming language appears in
`SKILL.md` unless tagged `[JUSTIFIED: ...]` or shown inside a
`risky-language-reference` example block.

### Monitor sources

```bash
# Safe local dry run (classifies only, never opens issues, never writes state):
python monitors/monitor.py --dry-run

# Establish/update local baseline state after a reviewed change:
python monitors/monitor.py --write --framework nist-ai-rmf-1.0
```

In GitHub Actions the monitor runs on a weekly schedule with `GITHUB_TOKEN` and
`GITHUB_REPOSITORY` set automatically, and opens issues for review-worthy
changes. It runs **read-only against the repo** — it never commits state to
`main`.

## How change monitoring works

For each source in a skill's `sources.yaml`, the monitor records reachability,
HTTP status, a SHA-256 of the page/file, the page title, and any detected
version / publication date (via `expected_metadata` regex hints). It compares
the new observation to `source_state.json` and classifies the change as exactly
one of:

| Classification | Action | Meaning |
|---|:--:|---|
| `no_change` | none | All tracked signals identical (or first-run baseline). |
| `cosmetic_page_change` | none | Body hash changed but title/version/date stable. |
| `source_unreachable` | **issue** | Fetch failed or non-2xx response. |
| `metadata_change` | **issue** | Title/date changed, version unchanged. |
| `related_resource_change` | **issue** | Change on a `related` (non-canonical) source. |
| `ambiguous_requires_review` | **issue** | Change detected but not confidently classified. |
| `errata_or_patch` | **PR** | Patch-level version bump or "errata" detected. |
| `new_framework_version` | **PR** | Major/minor version increase. |

**Division of labor:** version drift (the bottom two rows) has a deterministic
fix, so it is handled by `propose-update.yml`, which opens a **pull request** —
not an issue. Everything else has no automated fix, so the monitor opens an
**issue** for a human to triage. The monitor still logs version drift for
visibility but does not duplicate it as an issue.

## Maintenance flows

Two complementary flows, split by whether the change has a deterministic fix.

### A. Version drift → automated pull request (`propose-update.yml`)

1. The proposer detects that a framework's pinned version differs from the
   version on its live canonical source.
2. It deterministically bumps `version` in `frameworks.yaml` and
   `framework_profile.yaml`, adds a `changelog.md` entry, and refreshes
   `source_state.json`.
3. It runs `validate_skills.py`, then opens a **pull request**.
4. You review the diff, confirm against the official source, and approve. If the
   *substantive* content changed, you update `SKILL.md` in the same PR — the
   automation only bumps the version number, it does not rewrite framework text.

### B. Everything else → GitHub issue (`monitor.yml`)

1. The monitor detects a non-version change with no automated fix
   (`source_unreachable`, `metadata_change`, `related_resource_change`,
   `ambiguous_requires_review`) and **opens an issue** (deduplicated by title).
2. A maintainer (optionally with Claude) verifies it against the official source
   and, if warranted, opens a **pull request** with the change.

In both cases `validation` must pass and **nothing is auto-pushed to `main`.**

## Adding a new framework

1. Add an entry to [`frameworks.yaml`](frameworks.yaml) with: `id`, `name`,
   `version`, `skill_dir`, `profile`, `sources`, and `state` paths.
2. Create `skills/<id>/` with the six required members. Copy an existing skill
   folder as a starting point:
   ```bash
   cp -r skills/nist-csf-2.0 skills/<new-framework-id>
   ```
3. Edit all six files for the new framework:
   - `SKILL.md` — update Purpose, Scope, and Framework-Specific Workflows.
   - `framework_profile.yaml` — set `framework_id`, `version`, `publisher`,
     `official_structure`.
   - `sources.yaml` — add at least one canonical source with `expected_metadata`
     hints.
   - `source_state.json` — seed all source entries with `null` values.
   - `changelog.md` — add an initial entry.
   - `tests/test_skill.py` — update the `FRAMEWORK_ID` constant and any
     framework-specific assertions.
4. Run the full validation suite:
   ```bash
   python validation/validate_skills.py
   python -m pytest skills -q
   ```

## Notes & limitations

- Version/date detection uses conservative regex heuristics; when uncertain the
  monitor prefers `ambiguous_requires_review` over guessing.
- Skills embed no official framework text — content accuracy depends on
  consulting the official sources referenced in `sources.yaml`.
- The pinned `version` / `publication_date` in each `framework_profile.yaml`
  should be verified against the canonical source before being relied upon.
