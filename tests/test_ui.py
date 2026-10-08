from __future__ import annotations

import json
import threading
import urllib.request

from ui import make_server


def _server(tmp_path):
    server = make_server("127.0.0.1", 0, str(tmp_path / "ui.db"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _json(url, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def test_ui_serves_index_and_manages_refs(tmp_path):
    server, base = _server(tmp_path)
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            html = resp.read().decode()
            assert "agent-milestone" in html
            assert 'data-tab="diff"' in html
            assert 'id="diffBase"' in html
            assert "tree-folder" in html
            assert "icon('branch')" in html

        _json(base + "/api/checkpoint", "POST", {
            "name": "main",
            "steps": [{"role": "user", "content": "hello"}],
        })
        _json(base + "/api/branch", "POST", {"name": "feature", "from_ref": "main"})
        refs = _json(base + "/api/refs")
        assert {ref["name"] for ref in refs} == {"main", "feature"}

        chinese = _json(base + "/api/checkpoint", "POST", {
            "name": "对账排查",
            "steps": [{"role": "user", "content": "检查对账"}],
        })
        assert chinese["ok"] is True
        detail = _json(base + "/api/ref/" + urllib.parse.quote("对账排查"))
        assert detail["ref"]["name"] == "对账排查"
        assert detail["steps"][0]["content"] == "检查对账"

        diff = _json(base + "/api/diff?left=main&right=feature")
        assert diff["left_only_count"] == 0
        assert diff["right_only_count"] == 0

        # Rollback feature to main, then undo the rollback.
        _json(base + "/api/checkpoint", "POST", {
            "name": "feature",
            "steps": [{"role": "user", "content": "feature change"}],
        })
        rolled = _json(base + "/api/rollback", "POST", {"name": "feature", "to_ref": "main"})
        assert rolled["target"] == "main"
        undone = _json(base + "/api/undo", "POST", {"name": "feature"})
        assert undone["undid"] == "rollback"
        moved = _json(base + "/api/set_parent", "POST", {"name": "feature", "parent_ref": "main"})
        assert moved["parent_ref"] == "main"
    finally:
        server.shutdown()
        server.server_close()
