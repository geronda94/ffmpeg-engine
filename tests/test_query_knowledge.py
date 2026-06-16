"""Tests for core/query_knowledge.py — Entity matching, creation, and filter merging."""

import json
import sys
import os
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.query_knowledge import QueryKnowledge


def test_match_entity_by_alias():
    """Entity matching finds correct entity by alias substring."""
    kb = QueryKnowledge()
    kb._data = {
        "orthodox": {
            "jesus_christ": {
                "aliases": ["иисус христос", "христос", "спаситель", "jesus christ"],
                "queries": ["иисус христос икона", "спаситель православная икона"],
                "source": "icon",
                "color": "gold",
                "filters": {"exclude_tags": [], "require_tags": []},
                "created_by": "human",
            }
        }
    }

    # Matching by alias (exact word match)
    entity = kb.match_entity("икона спаситель в золотом свете", "orthodox")
    assert entity is not None, "Should match 'спаситель' alias as standalone word"
    assert entity["key"] == "jesus_christ"
    assert entity["source"] == "icon"

    # Matching morphological form (спасителя — separate alias)
    kb._data["orthodox"]["jesus_christ"]["aliases"].append("спасителя")
    entity = kb.match_entity("икона спасителя в золотом свете", "orthodox")
    assert entity is not None, "Should match 'спасителя' alias"

    # No match
    entity = kb.match_entity("абстрактное описание природы", "orthodox")
    assert entity is None, "Should not match any alias"


def test_word_boundary_matching():
    """Word boundary prevents substring false positives."""
    kb = QueryKnowledge()
    kb._data = {
        "lifestyle": {
            "wellness_fitness": {
                "aliases": ["спорт", "sport", "fitness", "workout"],
                "queries": [],
                "source": "stock",
                "color": "green",
                "filters": {"exclude_tags": [], "require_tags": []},
                "created_by": "human",
            },
            "travel": {
                "aliases": ["travel", "trip", "vacation", "passport"],
                "queries": [],
                "source": "stock",
                "color": "blue",
                "filters": {"exclude_tags": [], "require_tags": []},
                "created_by": "human",
            },
        }
    }

    # "sport" in "passport" should NOT match wellness_fitness
    entity = kb.match_entity("passport travel", "lifestyle")
    assert entity is not None, "Should match 'travel'"
    assert entity["key"] == "travel", f"Expected 'travel', got {entity['key']}"

    # "sport" alone should match
    entity = kb.match_entity("спорт", "lifestyle")
    assert entity is not None, "Should match 'спорт'"
    assert entity["key"] == "wellness_fitness"


def test_entity_creation():
    """Creating entities works and saves to disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        kb = QueryKnowledge(config_dir=tmpdir)

        # Create entity via API
        kb.create_entity("orthodox", "st_test", {
            "aliases": ["тестовый святой", "test saint"],
            "queries": ["тестовая икона", "test icon"],
            "source": "icon",
            "color": "gold",
            "filters": {"exclude_tags": ["bad"], "require_tags": ["good"]},
        })

        # Verify in memory
        entity = kb.match_entity("тестовый святой молитва", "orthodox")
        assert entity is not None
        assert entity["key"] == "st_test"

        # Verify on disk
        fp = Path(tmpdir) / "orthodox.json"
        assert fp.exists(), "File should be saved to disk"

        with open(fp) as f:
            on_disk = json.load(f)
        assert "st_test" in on_disk
        assert on_disk["st_test"]["queries"] == ["тестовая икона", "test icon"]


def test_filter_update():
    """Updating filters for an entity works."""
    kb = QueryKnowledge()
    kb._data = {
        "orthodox": {
            "theotokos": {
                "aliases": ["богородица"],
                "queries": [],
                "source": "icon",
                "color": "gold",
                "filters": {"exclude_tags": ["old_bad"], "require_tags": ["old_good"]},
                "created_by": "human",
            }
        }
    }

    kb.update_filters("orthodox", "theotokos",
                       add_exclude_tags=["new_bad"],
                       add_require_tags=["new_good"])

    entity = kb._data["orthodox"]["theotokos"]
    filters = entity["filters"]
    assert "old_bad" in filters["exclude_tags"], "Should keep existing filters"
    assert "new_bad" in filters["exclude_tags"], "Should add new filters"
    assert "old_good" in filters["require_tags"]
    assert "new_good" in filters["require_tags"]


def test_mismatch_recording():
    """Recording mismatches increments counter."""
    kb = QueryKnowledge()
    kb._data = {
        "orthodox": {
            "jesus_christ": {
                "aliases": ["христос"],
                "queries": [],
                "source": "icon",
                "color": "gold",
                "filters": {},
                "created_by": "human",
            }
        }
    }

    kb.record_mismatch("orthodox", "jesus_christ")
    kb.record_mismatch("orthodox", "jesus_christ")

    assert kb._data["orthodox"]["jesus_christ"]["mismatch_count"] == 2


def test_multi_channel():
    """Entities are isolated by channel."""
    kb = QueryKnowledge()
    kb._data = {
        "orthodox": {
            "cross": {
                "aliases": ["крест", "cross"],
                "queries": ["православный крест"],
                "source": "stock",
                "color": "gold",
                "filters": {},
                "created_by": "human",
            }
        },
        "news": {
            "breaking_news": {
                "aliases": ["breaking news", "emergency"],
                "queries": ["breaking news report"],
                "source": "news",
                "color": "red",
                "filters": {},
                "created_by": "human",
            }
        }
    }

    # Orthodox match
    assert kb.match_entity("православный крест", "orthodox") is not None
    assert kb.match_entity("православный крест", "news") is None

    # News match
    assert kb.match_entity("breaking news report", "news") is not None
    assert kb.match_entity("breaking news report", "orthodox") is None


if __name__ == "__main__":
    test_match_entity_by_alias()
    test_word_boundary_matching()
    test_entity_creation()
    test_filter_update()
    test_mismatch_recording()
    test_multi_channel()
    print("✅ All 6 tests passed!")
