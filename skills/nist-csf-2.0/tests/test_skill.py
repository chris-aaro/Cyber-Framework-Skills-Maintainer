"""Tests for the NIST CSF 2.0 skill."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from common.utils import find_framework, load_yaml  # noqa: E402
from validation.validate_skills import validate_framework  # noqa: E402

FRAMEWORK_ID = "nist-csf-2.0"


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


def test_has_six_functions():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    functions = {f["id"] for f in profile["official_structure"]["functions"]}
    assert functions == {"GV", "ID", "PR", "DE", "RS", "RC"}, functions


def test_focus_areas_present():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    focus = set(profile.get("focus_areas", []))
    for expected in {
        "cybersecurity outcomes",
        "current and target profiles",
        "governance",
        "program maturity",
        "roadmaps",
    }:
        assert expected in focus, f"missing focus area: {expected}"


def test_has_canonical_source():
    fw = find_framework(FRAMEWORK_ID)
    sources = load_yaml(fw["sources"])
    assert len(sources.get("canonical_sources", [])) >= 1
