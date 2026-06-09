"""
references/transforms.py

Deterministic transforms that turn an official machine-readable framework
artifact into the split, diffable reference files a skill bundles. No Claude and
no network here — pure functions over already-downloaded data, so they are cheap
and unit-testable.

Each transform takes the parsed artifact plus a framework dict and returns:

    (index: dict, files: dict[str, object])

where `index` is written to references/index.json and `files` maps a
repo-relative-to-references path -> JSON-serializable content.

Add a new framework's transform by writing a function here and registering it in
TRANSFORMS, then pointing the framework's structured_content source at it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

# {{ insert: param, ac-02_odp.01 }} -> resolved against the control's parameters.
_PARAM_INSERT = re.compile(r"\{\{\s*insert:\s*param,\s*([^}\s]+)\s*\}\}")


def _param_label(param: dict) -> str:
    """Human-readable label for an OSCAL parameter (assignment or selection)."""
    if param.get("label"):
        return param["label"]
    select = param.get("select")
    if select:
        how = select.get("how-many")
        choices = [c for c in select.get("choice", [])]
        joined = " | ".join(choices)
        if how == "one-or-more":
            return f"selection (one or more): {joined}"
        return f"selection (one): {joined}"
    return param.get("id", "organization-defined")


def _resolve_params(text: str, labels: dict[str, str]) -> str:
    """Replace OSCAL param-insert tokens with readable [parameter: label] text."""
    def repl(m: re.Match) -> str:
        pid = m.group(1).strip()
        return f"[parameter: {labels.get(pid, pid)}]"

    return _PARAM_INSERT.sub(repl, text or "").strip()


def _collect_param_labels(control: dict) -> dict[str, str]:
    return {p["id"]: _param_label(p) for p in control.get("params", []) if "id" in p}


def _find_part(parts: list[dict], name: str) -> dict | None:
    for p in parts or []:
        if p.get("name") == name:
            return p
    return None


def _build_statement(part: dict | None, labels: dict[str, str]) -> list[dict]:
    """Flatten a `statement` part subtree into an ordered, nested list."""
    if not part:
        return []
    items = []
    for child in part.get("parts", []) or []:
        if child.get("name") not in ("item", "statement"):
            continue
        node: dict[str, Any] = {"id": child.get("id", "")}
        if child.get("prose"):
            node["prose"] = _resolve_params(child["prose"], labels)
        sub = _build_statement(child, labels)
        if sub:
            node["children"] = sub
        items.append(node)
    return items


def _control_to_ref(control: dict, family: dict) -> dict:
    """Reduce one OSCAL control (or enhancement) to a compact reference record."""
    labels = _collect_param_labels(control)
    parts = control.get("parts", [])
    statement_part = _find_part(parts, "statement")
    guidance_part = _find_part(parts, "guidance")

    ref: dict[str, Any] = {
        "id": control.get("id"),
        "title": control.get("title"),
        "family_id": family.get("id"),
    }
    params = [
        {"id": p["id"], "label": _param_label(p)}
        for p in control.get("params", [])
        if "id" in p
    ]
    if params:
        ref["parameters"] = params
    statement = _build_statement(statement_part, labels)
    if statement:
        ref["statement"] = statement
    if guidance_part and guidance_part.get("prose"):
        ref["guidance"] = _resolve_params(guidance_part["prose"], labels)
    enhancements = [
        _control_to_ref(enh, family) for enh in control.get("controls", []) or []
    ]
    if enhancements:
        ref["enhancements"] = enhancements
    return ref


def oscal_catalog_split(artifact: dict, framework: dict) -> tuple[dict, dict]:
    """
    Transform an OSCAL catalog (e.g. NIST SP 800-53) into:
      references/index.json
      references/controls/<family>.json   (one per control family)
    """
    catalog = artifact["catalog"]
    meta = catalog.get("metadata", {})
    version = str(meta.get("version", "")).strip()

    files: dict[str, object] = {}
    family_entries = []
    total_controls = 0

    for group in catalog.get("groups", []):
        family = {"id": group.get("id"), "title": group.get("title")}
        controls = [
            _control_to_ref(c, family) for c in group.get("controls", []) or []
        ]
        # Count base controls + enhancements for an honest total.
        def _count(cs):
            n = 0
            for c in cs:
                n += 1 + _count(c.get("enhancements", []))
            return n

        fam_count = _count(controls)
        total_controls += fam_count
        rel = f"controls/{family['id']}.json"
        files[rel] = {
            "family_id": family["id"],
            "family_title": family["title"],
            "controls": controls,
        }
        family_entries.append(
            {
                "id": family["id"],
                "title": family["title"],
                "file": rel,
                "control_count": fam_count,
            }
        )

    index = {
        "framework_id": framework["id"],
        "version": version,
        "title": meta.get("title"),
        "source_last_modified": meta.get("last-modified"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "control_family_count": len(family_entries),
        "control_count": total_controls,
        "families": family_entries,
    }
    return index, files


# Registry: transform name (declared in sources.yaml) -> callable.
TRANSFORMS: dict[str, Callable[[dict, dict], tuple[dict, dict]]] = {
    "oscal_catalog_split": oscal_catalog_split,
}
