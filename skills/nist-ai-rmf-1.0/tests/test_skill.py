"""Tests for the NIST AI RMF 1.0 skill."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from common.utils import find_framework, load_yaml  # noqa: E402
from validation.validate_skills import validate_framework  # noqa: E402

FRAMEWORK_ID = "nist-ai-rmf-1.0"


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


def test_has_four_functions():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    functions = {f["id"] for f in profile["official_structure"]["functions"]}
    assert functions == {"GOVERN", "MAP", "MEASURE", "MANAGE"}, functions


def test_seven_trustworthiness_characteristics():
    fw = find_framework(FRAMEWORK_ID)
    profile = load_yaml(fw["profile"])
    chars = profile["official_structure"]["trustworthiness_characteristics"]
    assert len(chars) == 7, f"expected 7 characteristics, got {len(chars)}"


def test_has_canonical_source():
    fw = find_framework(FRAMEWORK_ID)
    sources = load_yaml(fw["sources"])
    assert len(sources.get("canonical_sources", [])) >= 1
