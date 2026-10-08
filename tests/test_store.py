from __future__ import annotations

import json

import pytest

from store import TrailStore, step_hash

BASE = [
    {"role": "user", "content": "查一下对账差异"},
    {"role": "assistant", "content": "先查 Hive"},
    {"role": "tool", "tool_name": "query_hive", "tool_args": {"sql": "select 1"}},
]


def test_checkpoint_and_checkout_roundtrip():
    store = TrailStore(":memory:", redact=False)
    tip = store.checkpoint("main", BASE)
    assert len(tip) == 64
    assert store.checkout("main") == BASE


def test_step_hash_is_stable_and_parent_sensitive():
    assert step_hash(BASE[0]) == step_hash(BASE[0])
    assert step_hash(BASE[0], "a") != step_hash(BASE[0], "b")


def test_branch_and_diff_share_prefix():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.checkpoint("main-checkpoint", BASE, parent_ref="main")
    store.checkpoint("alt", BASE[:2] + [{"role": "tool", "tool_name": "query_hbase", "tool_args": {"table": "t"}}])
    store.branch("feature", "main")

    assert any(ref["name"] == "feature" and ref["kind"] == "branch" for ref in store.list_refs())
    main_checkpoint = next(r for r in store.list_refs() if r["name"] == "main-checkpoint")
    feature = next(r for r in store.list_refs() if r["name"] == "feature")
    assert main_checkpoint["parent_ref"] == "main"
    assert feature["parent_ref"] == "main"
    diff = store.diff("main", "alt")
    assert diff["common_steps"] == 2
    assert diff["left_only"][0]["tool_name"] == "query_hive"
    assert diff["right_only"][0]["tool_name"] == "query_hbase"


def test_checkpoint_advances_existing_branch_without_converting_kind():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.branch("feature", "main")
    store.checkpoint("feature", BASE + [{"role": "assistant", "content": "继续排查"}])
    ref = next(r for r in store.list_refs() if r["name"] == "feature")
    assert ref["kind"] == "branch"
    assert ref["steps"] == len(BASE) + 1


def test_rename_delete_and_reflog():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.rename("main", "renamed")
    assert store.checkout("renamed") == BASE
    with pytest.raises(KeyError):
        store.checkout("main")
    store.delete("renamed")
    assert store.reflog()[0]["operation"] == "delete"


def test_rollback_and_undo_last_are_history_preserving():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    feature = BASE + [{"role": "assistant", "content": "feature change"}]
    store.branch("feature", "main")
    store.checkpoint("feature", feature)
    assert len(store.checkout("feature")) == len(feature)

    result = store.rollback("feature", "main")
    assert result["target"] == "main"
    assert store.checkout("feature") == BASE

    undone = store.undo_last("feature")
    assert undone["undid"] == "rollback"
    assert store.checkout("feature") == feature


def test_set_parent_moves_ref_into_branch_folder():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.checkpoint("child", BASE, parent_ref="main")
    store.set_parent("child", "main")
    assert next(r for r in store.list_refs() if r["name"] == "child")["parent_ref"] == "main"
    store.set_parent("child", None)
    assert next(r for r in store.list_refs() if r["name"] == "child")["parent_ref"] is None


def test_replay_is_dry_run_and_never_executes_tools():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    plan = store.replay("main")
    assert plan["execute"] is False
    assert plan["actions"][2]["type"] == "tool_call"
    assert plan["actions"][2]["status"] == "dry_run"
    with pytest.raises(ValueError):
        store.replay("main", execute=True)


def test_gc_removes_only_unreachable_steps():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.checkpoint("alt", BASE[:2] + [{"role": "tool", "tool_name": "query_hbase"}])
    store.delete("alt")
    before = store.stats()["steps"]
    result = store.gc(dry_run=False)
    assert result["deleted"] == 1
    assert store.stats()["steps"] == before - 1


def test_redaction_happens_before_hashing_and_storage():
    store = TrailStore(":memory:", redact=True)
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    store.checkpoint("secret", [{"role": "user", "content": f"api_key={secret}"}])
    payload = json.dumps(store.checkout("secret"), ensure_ascii=False)
    assert secret not in payload
    assert "REDACTED" in payload


def test_migration_from_v1_milestones_table(tmp_path):
    import sqlite3

    db = tmp_path / "v1.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE steps (
            hash TEXT PRIMARY KEY, role TEXT NOT NULL, content TEXT DEFAULT '',
            tool_name TEXT, tool_args TEXT, tool_result TEXT, parent_hash TEXT
        );
        CREATE TABLE milestones (name TEXT PRIMARY KEY, step_hash TEXT NOT NULL);
        """
    )
    conn.commit()
    conn.close()

    store = TrailStore(str(db), redact=False)
    assert store.stats()["schema_version"] == 3
    store.checkpoint("main", BASE)
    assert store.checkout("main") == BASE


def test_checkpoint_accepts_non_string_content():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", [{"role": "user", "content": {"text": "结构化输入", "n": 1}}])
    out = store.checkout("main")
    assert out[0]["role"] == "user"
    assert isinstance(out[0]["content"], str)
    assert "结构化输入" in out[0]["content"]


def test_checkpoint_rejects_missing_parent_ref():
    store = TrailStore(":memory:", redact=False)
    with pytest.raises(KeyError):
        store.checkpoint("child", BASE, parent_ref="does-not-exist")
    assert all(ref["name"] != "child" for ref in store.list_refs())


def test_rename_reparents_children():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.checkpoint("child", BASE, parent_ref="main")
    store.rename("main", "main2")
    child = next(r for r in store.list_refs() if r["name"] == "child")
    assert child["parent_ref"] == "main2"


def test_delete_clears_children_parent_ref():
    store = TrailStore(":memory:", redact=False)
    store.checkpoint("main", BASE)
    store.checkpoint("child", BASE, parent_ref="main")
    store.delete("main")
    child = next(r for r in store.list_refs() if r["name"] == "child")
    assert child["parent_ref"] is None
