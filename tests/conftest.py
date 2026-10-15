import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURE_CORPUS = ROOT / "tests" / "fixtures" / "corpus_logistics.json"
REAL_CORPUS = ROOT / "data" / "corpus.json"


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    """Every test gets: a frozen fixture corpus (so rewriting data/corpus.json for a new topic never breaks the
    deterministic tests) and throw-away SQLite / output paths (so tests never touch var/ or outputs/)."""
    from rdi import config
    from rdi.services import search_backend

    monkeypatch.setattr(config, "CORPUS_PATH", FIXTURE_CORPUS)
    monkeypatch.setattr(config, "APPROVAL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outputs")
    (tmp_path / "outputs").mkdir()
    search_backend.get_backend.cache_clear()
    yield
    search_backend.get_backend.cache_clear()


@pytest.fixture
def real_corpus(monkeypatch):
    """Opt-in: point the search backend at the REAL data/corpus.json (used by tests/test_corpus.py)."""
    from rdi import config
    from rdi.services import search_backend

    monkeypatch.setattr(config, "CORPUS_PATH", REAL_CORPUS)
    search_backend.get_backend.cache_clear()
    return REAL_CORPUS
