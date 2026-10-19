import json

from papermind.db.core import connect, init_db
from papermind.importers.chatgpt_json import looks_like_chatgpt_export, parse_conversations
from papermind.pipeline.ingest import import_text


def _conv():
    def node(i, parent, role, text, children=(), attach=False):
        return {
            "id": i, "parent": parent, "children": list(children),
            "message": {
                "author": {"role": role}, "create_time": 1780000000 + len(i),
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {"attachments": [{"name": "x.pdf"}]} if attach else {},
            },
        }  # fmt: skip

    mapping = {
        "root": {"id": "root", "parent": None, "children": ["u1"], "message": None},
        "u1": node("u1", "root", "user", "请总结 https://arxiv.org/abs/2601.00001 这篇论文", ["a1"]),
        "a1": node("a1", "u1", "assistant", "**论文定位**：测试论文。\n- **背景**：问题。", ["u2"]),
        "u2": node("u2", "a1", "user", "他们的样本量是多少？", ["a2"]),
        "a2": node("a2", "u2", "assistant", "样本量 20 名患者。", ["u3x"]),
        # abandoned branch must be ignored: current_node points to a2's path
        "u3x": node("u3x", "a2", "user", "abandoned", []),
    }
    return {"title": "Test chat", "create_time": 1780000000, "current_node": "a2", "mapping": mapping}


def test_parse_and_import_chatgpt_export():
    raw = json.dumps([_conv()])
    assert looks_like_chatgpt_export(raw)
    ((meta, turns),) = parse_conversations(raw)
    assert meta["title"] == "Test chat"
    assert [t.user[:3] for t in turns] == ["请总结", "他们的"]
    init_db()
    conn = connect()
    r = import_text(conn, raw, filename="conversations.json")
    assert r.new == 1 and r.followups == 1
    p = conn.execute("SELECT * FROM paper").fetchone()
    assert p["arxiv_id"] == "2601.00001"
