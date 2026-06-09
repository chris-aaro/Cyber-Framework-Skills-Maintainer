# Weekly maintenance routine (playbook for the scheduled Claude Code agent)

You are running as a **scheduled Claude Code routine** for the Cyber Framework
Claude Skills Maintainer repository. Your job, once a week, is to keep each
framework skill current with its official source — including the **substantive
content**, which the deterministic GitHub Actions cannot do.

You operate on your Claude Code plan (not a metered API). Work carefully and
conservatively: you open **pull requests** for a human to approve. You never push
to `main`.

## Hard guardrails (read first)

- **Never invent** framework requirements, control/subcategory IDs, mappings, or
  official language. Every `[OFFICIAL]` claim must come from a bundled reference
  file (produced by `references/ingest.py`) or a cited official source.
- **Distinguish** official text from interpretation/implementation/mapping
  rationale, per each skill's `## Official vs. Interpretation` convention.
- **Do not push to `main`.** Open a PR per framework and stop.
- **Validation must pass** before you open a PR. If you cannot make it pass
  honestly, open a *draft* PR describing the blocker instead of forcing it.
- **One PR per framework.** Do not bundle unrelated frameworks together.
- Avoid the over-claiming phrases the validator flags (e.g. "NIST mandates",
  "guarantees compliance") unless quoting them with a `[JUSTIFIED: ...]` note.

## Setup

1. Ensure a clean checkout of the default branch:
   - `git fetch origin && git checkout main && git pull --ff-only`
2. Create/activate the Python environment:
   - `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
   - Use `.venv/bin/python` for all commands below.

## Step 1 — Detect drift

Run the monitor (read-only, no issues created locally):

```
.venv/bin/python monitors/monitor.py --dry-run
```

Note any framework that reports `version_pin_mismatch` — that is a framework
whose pinned version is behind the live official source. Also note any
`source_unreachable` / `metadata_change` / `related_resource_change` /
`ambiguous_requires_review` lines: those are **not** your job to fix here — the
`monitor.yml` workflow opens issues for them. You only act on **version drift**.

If no framework shows `version_pin_mismatch`, also run
`.venv/bin/python references/ingest.py --check` to catch content errata where the
version string did not change. If everything is current, **stop — nothing to do
this week.**

## Step 2 — For each framework with version drift

Do the following on a fresh branch named `auto/update-<framework-id>-<new-version>`.

1. **Bump the version** to the detected version in **both**:
   - `frameworks.yaml` (the framework's `version:`)
   - `skills/<id>/framework_profile.yaml` (`version:`, and `publication_date:` if
     you can confirm it from the official source — otherwise leave a `# verify`
     comment; do not guess a date).

2. **Regenerate the bundled content** (only for skills with
   `content_mode: structured`):
   ```
   .venv/bin/python references/ingest.py --framework <id>
   ```
   This rewrites `skills/<id>/references/`. Inspect the diff:
   ```
   git --no-pager diff --stat skills/<id>/references/
   ```

3. **Understand what changed — from authoritative sources, not memory.**
   - Read the official change list for the new version (the canonical source
     pages in `skills/<id>/sources.yaml` link to NIST's "what changed" / release
     notes; fetch them).
   - Cross-check against the reference diff (which controls/outcomes/parameters
     were added, removed, or revised).

4. **Author the substantive update** (this is the part only you can do):
   - Add a dated entry to `skills/<id>/changelog.md` summarizing the change:
     what version, what NIST changed (cite the official change list), and that the
     bundled reference content was regenerated. Keep official facts cited; mark any
     of your own framing as interpretation.
   - If the framework's **structure** changed (e.g. a new control family, a new
     CSF function/category, renamed elements), update the affected parts of
     `SKILL.md` (`## Framework-Specific Workflows`, `## Reference Data`) and
     `framework_profile.yaml` `official_structure` to match — grounded in the
     reference files, labeled `[OFFICIAL]` only where attributable.
   - Do **not** paste large bodies of control text into `SKILL.md`; the content
     lives in `references/`. `SKILL.md` should point at it.

5. **Validate — must pass:**
   ```
   .venv/bin/python validation/validate_skills.py --framework <id>
   .venv/bin/python -m pytest -q
   ```
   Fix any failures (commonly: the reference index version must equal the bumped
   registry version). Do not weaken the validator to make it pass.

6. **Open the pull request:**
   ```
   git checkout -b auto/update-<id>-<new-version>
   git add -A
   git commit -m "Update <id>: <old> -> <new> (version + bundled content)"
   git push -u origin auto/update-<id>-<new-version>
   gh pr create --base main --label automated-update \
     --title "Update <id>: <old> -> <new>" --body "<summary>"
   ```
   The PR body must include: the version change, a concise summary of what
   changed (with citations to the official change list), confirmation that
   validation passed, and a reviewer checklist (confirm against the official
   source; check the changelog; review the references diff).

## Step 3 — Report

Finish with a short summary of: which frameworks were checked, which had drift,
the PR link(s) opened, and anything you deliberately did not touch (e.g.
non-version changes left for `monitor.yml`). Then stop and wait for human review.

## Notes / setup requirements for this routine

- The routine's environment needs `git` + `gh` authenticated with permission to
  push branches and open PRs on this repo (not `main` write).
- `validate.yml` will still run on the PR via its `push` trigger, independently
  re-checking your work.
- Keep token use low: the deterministic `ingest.py` already did the heavy
  parsing — review its diff and the official change list rather than re-reading
  entire framework documents.
