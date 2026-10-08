from __future__ import annotations

import json

from record import auto_name, parse_transcript


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_parse_transcript_links_tool_result(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": "查一下对账差异"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "先查 Hive"},
            {"type": "tool_use", "id": "t1", "name": "query_hive", "input": {"sql": "select 1"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "1 row"},
        ]}},
    ])
    steps = parse_transcript(str(transcript))
    assert steps[0]["role"] == "user"
    assert steps[1]["role"] == "assistant"
    assert steps[2]["role"] == "tool"
    assert steps[2]["tool_result"] == "1 row"


def test_parse_transcript_skips_malformed_lines(tmp_path):
    transcript = tmp_path / "session.jsonl"
    valid = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
    transcript.write_text("not json\n" + valid, encoding="utf-8")
    assert len(parse_transcript(str(transcript))) == 1


def test_auto_name_skips_command_messages():
    steps = [
        {"role": "user", "content": "/clear"},
        {"role": "user", "content": "排查昨天的对账差异"},
    ]
    assert auto_name(steps) == "排查昨天的对账差异"


def test_parse_transcript_reads_user_text_blocks(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "帮我看下这张表的分布"},
        ]}},
    ])
    steps = parse_transcript(str(transcript))
    assert steps == [{"role": "user", "content": "帮我看下这张表的分布"}]
