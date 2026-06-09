# Cyber Framework Claude Skills Maintainer

A **local-first, GitHub-based** system for maintaining framework-specific
[Claude Skills](https://docs.claude.com/) for cybersecurity and AI risk
frameworks, and for **monitoring the official sources** of those frameworks so
skills stay accurate over time.

Frameworks are registered in [`frameworks.yaml`](frameworks.yaml). The three
initial frameworks are:

| Framework | Skill | Version (pinned) | Bundled content |
|---|---|---|---|
| NIST SP 800-53 | [`skills/nist-sp-800-53`](skills/nist-sp-800-53) | 5.2.0 | structured (OSCAL) |
| NIST Cybersecurity Framework 2.0 | [`skills/nist-csf-2.0`](skills/nist-csf-2.0) | 2.0 | reference-only* |
| NIST AI Risk Management Framework 1.0 | [`skills/nist-ai-rmf-1.0`](skills/nist-ai-rmf-1.0) | 1.0 | reference-only* |

\* CSF 2.0 and AI RMF currently reference official sources by URL; bundling their
full structured content is a follow-up (see [Bundled content](#bundled-reference-content)).

**Scope:** this system targets **public-domain** frameworks (e.g. NIST). Embedding
full official text is only done because NIST works are public domain — do not add
copyrighted standards (ISO, PCI DSS, CIS, SOC 2) as bundled content.

New frameworks can be added by following [Adding a new framework](#adding-a-new-framework).

## Design philosophy: source fidelity

Every skill enforces two rules:

1. **Never invent** framework requirements, control/subcategory IDs, mappings, or
   official language. Official text comes from the bundled structured reference
   files (`references/`) or cited sources in `sources.yaml` — never reconstructed
   from memory.
2. **Always distinguish** official framework text (`[OFFICIAL]`) from
   `[INTERPRETATION]`, `[IMPLEMENTATION]` advice, and `[MAPPING RATIONALE]`.

The validator enforces structure and flags over-claiming language such as
"NIST mandates" or "guarantees compliance".

## Two halves: detection (GitHub) + authoring (Claude routine)

Keeping a skill current has a cheap, deterministic half and an intelligent half.
They live in different places on purpose:

- **GitHub Actions (deterministic, free):** monitor sources, detect drift, run the
  `validate` CI gate, host PR review. No Claude.
- **A weekly Claude Code routine (intelligent):** when a new version ships, fetch
  the new content, update the bundled references, draft the changelog/structure
  changes, validate, and open a PR. See
  [`routines/weekly-maintenance.md`](routines/weekly-maintenance.md).

> **Why a routine and not the Claude Code GitHub Action?** From **2026-06-15**,
> Anthropic's plan no longer covers the Claude Code GitHub Actions integration —
> in-Actions Claude becomes metered per-use SDK cost. A scheduled **routine** runs
> on your existing Claude Code plan, so the authoring half stays cost-effective
> while GitHub keeps doing the cheap deterministic work.

## Repository layout

```
frameworks.yaml              # registry of all frameworks (single source of truth)
requirements.txt             # PyYAML + pytest (everything else is stdlib)
pytest.ini
common/utils.py              # shared helpers: YAML/JSON IO, http_get, hashing
monitors/monitor.py          # fetch sources, classify changes, open issues
monitors/propose_update.py   # deterministic version-bump PR (manual fallback)
references/ingest.py         # download + transform official structured content
references/transforms.py     # per-format transforms (e.g. OSCAL -> split files)
validation/validate_skills.py# structure + guardrail + reference validation (CI gate)
routines/weekly-maintenance.md # playbook the weekly Claude Code routine runs
skills/<framework>/
  SKILL.md                   # the Claude Skill (guardrails + workflows)
  framework_profile.yaml     # id/version/structure/content_mode (must match registry)
  sources.yaml               # canonical + related + structured_content sources
  source_state.json          # last-observed snapshot per source (no DB)
  changelog.md               # Keep-a-Changelog history
  references/                # bundled structured content (structured skills only)
    index.json               #   self-describing manifest (version + family files)
    controls/<family>.json   #   split, diffable content for progressive disclosure
  tests/test_skill.py        # per-skill validation tests
.github/workflows/
  monitor.yml                # scheduled monitoring -> GitHub issues
  validate.yml               # push/PR -> validate skills + tests
  propose-update.yml         # manual deterministic version-bump fallback
```

No database and no cloud infrastructure beyond GitHub Actions are required.

## Bundled reference content

Skills with `content_mode: structured` bundle the framework's **full content** as
split, diffable JSON under `references/`, so Claude cites real official text
instead of recalling it from memory. `SKILL.md` stays thin and points at the data
(progressive disclosure: read `index.json`, then load only the family file you
need).

The content is produced deterministically by `references/ingest.py` from official
**machine-readable** artifacts (800-53 uses the public-domain OSCAL catalog from
`usnistgov/oscal-content`). Regenerate / verify:

```bash
python references/ingest.py --framework nist-sp-800-53   # download + transform + write
python references/ingest.py --check                       # report if on-disk content is stale
```

The reference `index.json` version must equal the registry version — the validator
enforces this, so a version bump and a content refresh always travel together.

> CSF 2.0 and AI RMF are not yet bundled (no clean public JSON identified; NIST's
> CPRT export is xlsx, which we avoid to keep dependencies to PyYAML only). They
> remain reference-only until a structured source + transform is added.

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
`risky-language-reference` example block. For `content_mode: structured` skills it
also confirms the `## Reference Data` section, that the reference index exists, and
that its version matches the registry and its listed family files are present.

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

Three channels, split by who can act on the change.

### A. Version drift → Claude Code routine opens a content PR (primary)

The weekly routine ([`routines/weekly-maintenance.md`](routines/weekly-maintenance.md))
detects that a framework's pinned version is behind its live source, then:
1. bumps `version` in `frameworks.yaml` + `framework_profile.yaml`;
2. regenerates the bundled `references/` via `references/ingest.py`;
3. drafts the `changelog.md` summary and any `SKILL.md`/structure updates,
   grounded in the official change list and the reference diff;
4. runs validation, opens **one PR per framework**.

You review and approve. Setup: create the routine with the `/schedule` skill,
pointing it at the playbook; its environment needs `git` + `gh` able to push
branches and open PRs (not `main` write).

### B. Non-version changes → GitHub issue (`monitor.yml`)

The monitor opens an **issue** (deduplicated by title) for changes with no
automated fix: `source_unreachable`, `metadata_change`, `related_resource_change`,
`ambiguous_requires_review`. A human triages.

### C. Deterministic version-bump → manual fallback (`propose-update.yml`)

If the routine is unavailable, trigger `propose-update.yml` by hand. It opens a PR
that bumps **only the version number** (no content update) — a stopgap, not the
primary path.

In all cases `validation` must pass and **nothing is auto-pushed to `main`.**

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
4. *(Optional, recommended)* bundle full content: add a `structured_content`
   source to `sources.yaml` with a `transform` registered in
   `references/transforms.py`, set `content_mode: structured` +
   `reference_index: references/index.json` in the profile, add a
   `## Reference Data` section to `SKILL.md`, then run
   `python references/ingest.py --framework <id>`.
5. Run the full validation suite:
   ```bash
   python validation/validate_skills.py
   python -m pytest -q
   ```

## Notes & limitations

- Version/date detection uses conservative regex heuristics; when uncertain the
  monitor prefers `ambiguous_requires_review` over guessing.
- Skills embed no official framework text — content accuracy depends on
  consulting the official sources referenced in `sources.yaml`.
- The pinned `version` / `publication_date` in each `framework_profile.yaml`
  should be verified against the canonical source before being relied upon.
