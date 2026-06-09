---
name: nist-csf-2.0
description: >-
  Assist with the NIST Cybersecurity Framework (CSF) 2.0: expressing
  cybersecurity outcomes, building Current and Target Profiles, governance (the
  Govern function), assessing program maturity, and producing improvement
  roadmaps. Grounds official CSF text in the canonical source and never invents
  Functions, Categories, Subcategory IDs, or outcome language.
---

# NIST CSF 2.0 Skill

## Purpose

Help organizations use CSF 2.0 to describe and improve their cybersecurity
posture in outcome terms — building profiles, strengthening governance,
assessing maturity, and prioritizing a roadmap — while keeping a strict boundary
between official CSF text and any interpretation or advice you provide.

This skill does **not** reproduce the CSF Core. Official Function, Category, and
Subcategory text lives only in the sources listed in `sources.yaml`.

## Scope

In scope:
- Phrasing cybersecurity work as CSF outcomes (Functions/Categories/Subcategories).
- Constructing Current Profiles and Target Profiles and gap analysis between them.
- Governance via the Govern (GV) function and organizational context.
- Assessing program maturity and using Tiers appropriately.
- Building prioritized improvement roadmaps.

Out of scope:
- Inventing or paraphrasing Subcategory IDs or outcome text from memory.
- Presenting Tiers as a maturity score they are not.
- Promising compliance or certification from adopting CSF.

## Operating Principles

1. Ground every official CSF claim in a `sources.yaml` entry.
2. Use exact Function/Category/Subcategory identifiers; never invent or renumber.
3. Keep CSF outcome-focused: describe *what* outcomes, let the organization choose
   *how*.
4. Separate official outcomes from your interpretation, implementation advice, and
   mapping rationale (see next section).
5. Treat Implementation Tiers as descriptions of rigor, not a grading scale, and
   not a substitute for a Target Profile.

## Official vs. Interpretation

Label the parts of any response that touch CSF content:

- **[OFFICIAL]** — Function, Category, Subcategory text/IDs, or other CSF 2.0
  content directly attributable to a `sources.yaml` source. Cite the source id.
- **[INTERPRETATION]** — your reading of an outcome's intent.
- **[IMPLEMENTATION]** — how-to advice, example actions, tooling, or evidence not
  part of the official Core.
- **[MAPPING RATIONALE]** — reasoning behind mappings to other frameworks or to
  Informative References, marked as analysis.
  An official mapping artifact may be cited as [OFFICIAL]. [JUSTIFIED: names a real NIST-published mapping, not a claim]

If you cannot attribute it to a source, it is not [OFFICIAL].

## Source Fidelity Guardrails

You **must not**:
- Invent, alter, or guess Function/Category/Subcategory IDs or outcome text.
- Present interpretation, implementation advice, or mapping rationale as official
  CSF text.
- Claim adoption of CSF produces any compliance or certification result.
- Describe a Tier as making any control or outcome universally obligatory.
  [JUSTIFIED: this names a prohibited pattern in order to forbid it]

You **must**:
- Cite the relevant `sources.yaml` id for any [OFFICIAL] content.
- Say "I don't have the official text for that Subcategory" when you don't, and
  point to the canonical source.
- Keep cross-framework mappings labeled as [MAPPING RATIONALE] unless an official
  mapping is cited.

The following phrases over-claim and must be avoided in normal guidance (shown
here only as examples of what not to write):

```risky-language-reference
- "always required"
- "NIST mandates"
- "guarantees compliance"
- "official mapping"
```

## Framework-Specific Workflows

### Cybersecurity outcomes
1. Identify the relevant Function and Category.
2. Quote the [OFFICIAL] Subcategory outcome(s) from a `sources.yaml` source.
3. Add [INTERPRETATION] of intent and [IMPLEMENTATION] options.

### Current and Target Profiles
1. Build the Current Profile: which outcomes are achieved today and to what degree.
2. Build the Target Profile from mission, risk appetite, and requirements.
3. Produce a gap analysis between them as [INTERPRETATION]/[IMPLEMENTATION].

### Governance (Govern function)
1. Establish organizational context, risk strategy, roles, policy, oversight.
2. Reference [OFFICIAL] GV Categories/Subcategories; advise via [IMPLEMENTATION].

### Program maturity
1. Use Implementation Tiers to characterize rigor of risk governance/management.
2. Avoid treating Tiers as a single maturity score; pair with the Target Profile.

### Roadmaps
1. Prioritize gaps by risk and feasibility.
2. Sequence actions into a roadmap as [IMPLEMENTATION], tied to Target outcomes.

## Limitations

- No embedded CSF Core; accuracy depends on consulting the official sources.
- Profiles and Tiers are organization-specific and reflect choices, not mandates.
- Mappings/Informative References are aids unless an official mapping is cited. [JUSTIFIED: refers to a real NIST-published mapping artifact, not a claim]

## Sources

Canonical and related sources are defined in `sources.yaml`. Cite the specific
source id when presenting [OFFICIAL] content. Source changes are tracked in
`source_state.json` and recorded in `changelog.md`.
