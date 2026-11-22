"""审计只读面。"""
from __future__ import annotations

from fastapi import APIRouter

from auth import AuthHeader, require_user
from db import connect

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
def list_audit(authorization: AuthHeader = None, limit: int = 100):
    require_user(authorization)
    limit = max(1, min(int(limit), 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/audit/actions")
def list_actions(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT action, COUNT(*) c FROM audit_trail
               GROUP BY action ORDER BY c DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/audit/lock-cutoff")
def lock_cutoff_trail(authorization: AuthHeader = None):
    """索锁截断只读面：争用痕（锁败痕）与写口截断命运核对。

    乙路径下未持锁写请求只在此留痕，不产生任何业务审计/业务行。
    """
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT lock_key, actor, action, detail, created_at
               FROM contention_log ORDER BY id DESC LIMIT 200"""
        ).fetchall()
        items = [dict(r) for r in rows]
        actors: dict[str, int] = {}
        for it in items:
            actors[it["actor"]] = actors.get(it["actor"], 0) + 1
        return {
            "items": items,
            "summary": {
                "cutoff_events": len(items),
                "by_actor": actors,
                "policy": "乙路径：未持锁 409 拒收，争用只记痕，正式零改",
            },
        }
