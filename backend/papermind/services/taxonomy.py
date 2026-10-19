"""Category tree management (topic facet)."""

from __future__ import annotations

import sqlite3

from papermind.resources.presets import NEURO_PRESET


def list_tree(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM paper_category pc WHERE pc.category_id = c.id) AS n_papers "
        "FROM category c WHERE c.facet = 'topic' ORDER BY c.position, c.id"
    ).fetchall()
    nodes = {r["id"]: {**dict(r), "children": []} for r in rows}
    roots: list[dict] = []
    for n in nodes.values():
        (nodes[n["parent_id"]]["children"] if n["parent_id"] in nodes else roots).append(n)
    return roots


def flat(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM category WHERE facet = 'topic' ORDER BY position, id").fetchall()


def ancestors(conn: sqlite3.Connection, cid: int) -> list[int]:
    out: list[int] = []
    cur = conn.execute("SELECT parent_id FROM category WHERE id = ?", (cid,)).fetchone()
    while cur and cur["parent_id"] and cur["parent_id"] not in out:
        out.append(cur["parent_id"])
        cur = conn.execute("SELECT parent_id FROM category WHERE id = ?", (cur["parent_id"],)).fetchone()
    return out


def top_level(conn: sqlite3.Connection, cid: int) -> int:
    chain = ancestors(conn, cid)
    return chain[-1] if chain else cid


def create(
    conn: sqlite3.Connection, name: str, description: str = "", parent_id: int | None = None, created_by: str = "user"
) -> int:
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM category WHERE facet='topic'").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO category(facet, name, parent_id, description, created_by, position) VALUES ('topic',?,?,?,?,?)",
        (name, parent_id, description, created_by, pos),
    )
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, cid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "description", "parent_id", "position")}
    if "parent_id" in allowed and allowed["parent_id"] is not None:
        if allowed["parent_id"] == cid or cid in ancestors(conn, allowed["parent_id"]):
            raise ValueError("cannot move a category under itself")
    for k, v in allowed.items():
        conn.execute(f"UPDATE category SET {k} = ? WHERE id = ?", (v, cid))
    if "name" in allowed or "description" in allowed:  # description vector is stale now
        conn.execute("DELETE FROM embedding WHERE owner_type = 'category' AND owner_id = ?", (cid,))
    conn.commit()


def delete(conn: sqlite3.Connection, cid: int) -> None:
    conn.execute(
        "UPDATE category SET parent_id = (SELECT parent_id FROM category WHERE id = ?) WHERE parent_id = ?", (cid, cid)
    )
    conn.execute("DELETE FROM category WHERE id = ?", (cid,))
    conn.commit()


def seed_preset(conn: sqlite3.Connection) -> list[int]:
    ids: list[int] = []
    for name, desc, children in NEURO_PRESET:
        pid = create(conn, name, desc, None, "preset")
        ids.append(pid)
        for cname, cdesc in children:
            ids.append(create(conn, cname, cdesc, pid, "preset"))
    return ids
