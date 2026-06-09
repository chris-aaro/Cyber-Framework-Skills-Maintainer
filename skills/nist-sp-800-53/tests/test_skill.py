"""Tests for the NIST SP 800-53 skill."""

import sys
from pathlib import Path

# Repo root = four levels up: tests/ -> skill/ -> skills/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from common.utils import find_framework, load_yaml  # noqa: E402
from validation.validate_skills import validate_framework  # noqa: E402

FRAMEWORK_ID = "nist-sp-800-53"


def test_skill_passes_validation():
    fw = find_framework(FRAMEWORK_ID)
    assert fw is not None, "framework not registered in frameworks.yaml"
    result = validate_framework(fw)
    assert result.ok, f"validation errors: {result.errors}"


def test_profile_matches_registry():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    assert profile["framework_id"] == FRAMEWORK_ID
    assert str(profile["version"]) == str(fw["version"])


def test_focus_areas_present():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    focus = set(profile.get("focus_areas", []))
    for expected in {
        "control interpretation",
        "implementation",
        "assessment evidence",
        "tailoring and overlays",
        "mappings",
    }:
        assert expected in focus, f"missing focus area: {expected}"


def test_has_canonical_source():
    fw = find_framework(FRAMEWORK_ID)
    sources = load_yaml(fw["sources"])
    assert len(sources.get("canonical_sources", [])) >= 1


def test_structured_reference_content():
    """800-53 bundles the full OSCAL-derived control catalog as references."""
    import json

    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    assert profile.get("content_mode") == "structured"
    index_path = REPO_ROOT / fw["skill_dir"] / profile["reference_index"]
    assert index_path.is_file(), "reference index missing; run references/ingest.py"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert str(index["version"]) == str(fw["version"])
    # 800-53 has 20 control families; spot-check a known one is present and non-empty.
    fam_ids = {f["id"] for f in index["families"]}
    assert {"ac", "au", "sc", "si"} <= fam_ids, fam_ids
    ac_file = index_path.parent / next(f["file"] for f in index["families"] if f["id"] == "ac")
    ac = json.loads(ac_file.read_text(encoding="utf-8"))
    ac1 = next(c for c in ac["controls"] if c["id"] == "ac-1")
    assert ac1["title"]
    assert ac1.get("guidance")
