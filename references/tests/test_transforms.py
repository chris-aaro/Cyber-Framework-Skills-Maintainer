"""Unit tests for references/transforms.py (no network)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from references.transforms import oscal_catalog_split  # noqa: E402

# Minimal OSCAL-shaped catalog with one family, one control + one enhancement,
# a parameter insert, statement items, and guidance.
FIXTURE = {
    "catalog": {
        "metadata": {
            "title": "Test Catalog",
            "version": "9.9.9",
            "last-modified": "2026-01-01T00:00:00.000-00:00",
        },
        "groups": [
            {
                "id": "ac",
                "title": "Access Control",
                "controls": [
                    {
                        "id": "ac-1",
                        "title": "Policy and Procedures",
                        "params": [{"id": "ac-01_odp", "label": "frequency"}],
                        "parts": [
                            {
                                "name": "statement",
                                "id": "ac-1_smt",
                                "parts": [
                                    {
                                        "name": "item",
                                        "id": "ac-1_smt.a",
                                        "prose": "Review the policy {{ insert: param, ac-01_odp }};",
                                    }
                                ],
                            },
                            {
                                "name": "guidance",
                                "id": "ac-1_gdn",
                                "prose": "Access control policy guidance.",
                            },
                        ],
                        "controls": [
                            {
                                "id": "ac-1.1",
                                "title": "Automated Policy",
                                "parts": [
                                    {
                                        "name": "statement",
                                        "id": "ac-1.1_smt",
                                        "parts": [
                                            {
                                                "name": "item",
                                                "id": "ac-1.1_smt.a",
                                                "prose": "Automate it.",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
}


def test_oscal_split_index_and_files():
    index, files = oscal_catalog_split(FIXTURE, {"id": "test-fw"})
    assert index["framework_id"] == "test-fw"
    assert index["version"] == "9.9.9"
    assert index["control_family_count"] == 1
    # base control + enhancement counted.
    assert index["control_count"] == 2
    assert index["families"][0]["file"] == "controls/ac.json"
    assert "controls/ac.json" in files


def test_param_insert_resolved():
    _, files = oscal_catalog_split(FIXTURE, {"id": "test-fw"})
    ac1 = files["controls/ac.json"]["controls"][0]
    stmt = ac1["statement"][0]["prose"]
    assert "[parameter: frequency]" in stmt
    assert "insert: param" not in stmt  # token fully resolved
    assert ac1["guidance"] == "Access control policy guidance."
    assert ac1["enhancements"][0]["id"] == "ac-1.1"
