from pathlib import Path

import pytest


@pytest.fixture
def unapproved_research_uses(monkeypatch):
    decision_path = "configs/missing_research_uses_test_fixture.json"
    assert not (Path(__file__).resolve().parents[1] / decision_path).exists()
    monkeypatch.setattr("glyph_features.workbench.materials.RESEARCH_USES", decision_path)