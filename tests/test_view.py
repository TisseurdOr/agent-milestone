from __future__ import annotations

from store import TrailStore
from view import render


def test_render_contains_refs_and_steps(tmp_path):
    db = tmp_path / "trails.db"
    store = TrailStore(str(db), redact=False)
    store.checkpoint("main", [{"role": "user", "content": "hello"}])
    store.branch("feature", "main")
    out = render(str(db), str(tmp_path / "trails.html"))
    html = open(out, encoding="utf-8").read()
    assert "main" in html
    assert "feature" in html
    assert "branch" in html
