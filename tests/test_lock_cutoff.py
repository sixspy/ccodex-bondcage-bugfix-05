"""索锁截断三红：解笼写口在未持锁时必须零拨付。

验收分两段，断言不得合并：
  第一段 争用断言——索锁失败者只在 contention_log 留争用痕，不进写口；
  第二段 截断命运断言——未持锁的拨付被正式拒收（409），零释放行、笼面零增、可用不为负、对账恒平。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db()
    yield


def _auth(c: TestClient, user: str) -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _make_passed_cage(c: TestClient, h: dict, party: str, amount: float) -> dict:
    """开户 → 入笼冻结 → 核验通过，返回可解笼的笼。"""
    assert c.post(
        "/api/bonds",
        headers=h,
        json={
            "party_key": party,
            "party_name": f"当事方{party}",
            "initial_deposit": amount * 2,
        },
    ).status_code == 200
    cage = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": party,
            "contract_no": f"HT-{party}-1",
            "amount": amount,
            "beneficiary": "受益人X",
            "cage_code": f"CG-{party}-LCK",
        },
    ).json()
    assert c.post(
        "/api/attestations",
        headers=h,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "OK"},
    ).status_code == 200
    return cage


def _releases_count(cage_id: int) -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM releases WHERE cage_id=?", (cage_id,)
        ).fetchone()["c"]


def _cage_row(cage_id: int):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM cages WHERE id=?", (cage_id,)
        ).fetchone()


# ---------------------------------------------------------------------------
# 失败测甲：索锁失败仍写入 —— 盯「失败仍写入」
# 未持锁一方的解笼请求不得产生任何 releases 行，笼面可用额零变动。
# ---------------------------------------------------------------------------
def test_甲_索锁失败仍写入_未持锁不得落拨付():
    c = TestClient(app)
    h_holder = _auth(c, "admin")
    h_rival = _auth(c, "clerk")
    cage = _make_passed_cage(c, h_holder, "P-LCK-A", 10000.0)
    cage_id = cage["id"]
    lock_key = f"cage:{cage_id}"

    # 持锁方先把笼锁占住（双会话同解的现场）
    assert c.post(
        "/api/locks/acquire", headers=h_holder, json={"lock_key": lock_key}
    ).status_code == 200

    before = _cage_row(cage_id)
    assert _releases_count(cage_id) == 0

    # 未持锁一方仍发起解笼拨付
    r = c.post("/api/releases", headers=h_rival, json={"cage_id": cage_id})

    # —— 第二段：截断命运断言 ——
    # 半成品拨付须拒收：索锁失败就是 409，不得 200 假绿
    assert r.status_code == 409, f"未持锁竟返回 {r.status_code}: {r.text}"
    assert _releases_count(cage_id) == 0, "索锁失败仍写入了 releases"
    after = _cage_row(cage_id)
    assert float(after["available"]) == float(before["available"]), "笼面可用额被改动"
    assert after["status"] == before["status"], "笼状态被改动"

    # —— 第一段：争用断言 ——
    # 后到一方只记争用：contention_log 有痕，且没有 cage_release 审计伪迹
    with connect() as conn:
        cont = conn.execute(
            "SELECT * FROM contention_log WHERE lock_key=? AND actor=?",
            (lock_key, "clerk"),
        ).fetchall()
        fake_audit = conn.execute(
            "SELECT COUNT(*) c FROM audit_trail WHERE action='cage_release'"
        ).fetchone()["c"]
    assert len(cont) == 1, "后到一方须恰好留一条争用痕"
    assert cont[0]["action"] == "争用"
    assert fake_audit == 0, "未持锁不得写 cage_release 审计"

    # 持锁方会话不重建：其释放自己持有的锁后仍可正常拨付
    assert c.post(
        "/api/locks/release", headers=h_holder, json={"lock_key": lock_key}
    ).status_code == 200
    ok = c.post("/api/releases", headers=h_holder, json={"cage_id": cage_id})
    assert ok.status_code == 200, ok.text
    assert _releases_count(cage_id) == 1


# ---------------------------------------------------------------------------
# 失败测乙：可用变负 —— 盯「可用变负」
# 锁被持有时，未持锁一方对同一笼连续两笔全额拨付；截断后可用额永远不小于 0。
# （缺陷代码下两次静默放行，第二笔把 available 扣成负数。）
# ---------------------------------------------------------------------------
def test_乙_索锁失败连拨_可用额不得为负():
    c = TestClient(app)
    h_holder = _auth(c, "admin")
    h_rival = _auth(c, "clerk")
    cage = _make_passed_cage(c, h_holder, "P-LCK-B", 6000.0)
    cage_id = cage["id"]
    lock_key = f"cage:{cage_id}"

    assert c.post(
        "/api/locks/acquire", headers=h_holder, json={"lock_key": lock_key}
    ).status_code == 200

    # 未持锁一方连开两笔全额解笼（双会话同解复现假绿）
    r1 = c.post("/api/releases", headers=h_rival, json={"cage_id": cage_id})
    r2 = c.post("/api/releases", headers=h_rival, json={"cage_id": cage_id})

    # —— 第二段：截断命运断言 ——
    assert r1.status_code == 409, f"第一笔未持锁拨付未被拒收: {r1.status_code}"
    assert r2.status_code == 409, f"第二笔未持锁拨付未被拒收: {r2.status_code}"

    row = _cage_row(cage_id)
    assert float(row["available"]) >= 0, f"可用额被削成负数: {row['available']}"
    assert float(row["available"]) == 6000.0, "未持锁写路径零改，可用额须原样"
    assert _releases_count(cage_id) == 0, "拒收路径不得留半成品拨付"

    # 账户侧同样不得被扣减
    with connect() as conn:
        acct = conn.execute(
            "SELECT * FROM bond_accounts WHERE party_key=?", ("P-LCK-B",)
        ).fetchone()
    assert float(acct["frozen"]) == 6000.0
    assert float(acct["balance"]) == 12000.0

    # 对账互证：可用 + 拨付 + 罚没 == 笼额
    recon = c.get(
        f"/api/reconcile/{cage['cage_code']}", headers=h_holder
    ).json()
    assert recon["balanced"] is True
    assert recon["gap"] == 0

    # —— 第一段：争用断言 —— 两次后到各留一条争用痕
    with connect() as conn:
        cont_n = conn.execute(
            "SELECT COUNT(*) c FROM contention_log WHERE lock_key=? AND actor=?",
            (lock_key, "clerk"),
        ).fetchone()["c"]
    assert cont_n == 2


# ---------------------------------------------------------------------------
# 争用失败测：双人同解抢笼锁 —— 盯「双人同解抢锁」
# 两个柜员会话并发对同一笼全额解笼：恰一方成功，后到一方 409 且只记争用。
# ---------------------------------------------------------------------------
def test_争用_双人同解_抢笼锁后到只记争用():
    c = TestClient(app)
    h1 = _auth(c, "admin")
    h2 = _auth(c, "clerk")
    cage = _make_passed_cage(c, h1, "P-LCK-C", 8000.0)
    cage_id = cage["id"]
    lock_key = f"cage:{cage_id}"

    holder_entered = threading.Event()
    rival_go = threading.Event()
    results: dict[str, object] = {}

    def holder_flow():
        # 先抢到笼锁，挂住不释放，等 rival 撞锁后再继续自己的拨付
        conn = connect()
        from locks import try_acquire

        ok = try_acquire(conn, lock_key, "admin")
        conn.commit()
        assert ok is True
        holder_entered.set()
        rival_go.wait(timeout=10)
        conn.close()
        try:
            r = c.post("/api/releases", headers=h1, json={"cage_id": cage_id})
            results["holder"] = (r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
        finally:
            c.post("/api/locks/release", headers=h1, json={"lock_key": lock_key})

    def rival_flow():
        holder_entered.wait(timeout=10)
        r = c.post("/api/releases", headers=h2, json={"cage_id": cage_id})
        results["rival"] = (r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
        rival_go.set()

    t1 = threading.Thread(target=holder_flow)
    t2 = threading.Thread(target=rival_flow)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not t1.is_alive() and not t2.is_alive(), "双会话线程未在时限内结束"

    # —— 第二段：截断命运断言 —— 一胜一拒，总额恰好一笔，可用额不出现负数/超扣
    assert results["holder"][0] == 200, results.get("holder")
    assert results["rival"][0] == 409, results.get("rival")
    assert _releases_count(cage_id) == 1, "双人同解只能落一笔拨付"
    row = _cage_row(cage_id)
    assert float(row["available"]) == 0.0
    assert row["status"] == "已解笼"

    recon = c.get(f"/api/reconcile/{cage['cage_code']}", headers=h1).json()
    assert recon["balanced"] is True

    # —— 第一段：争用断言 —— 后到 clerk 恰好一条争用痕，admin 无痕
    with connect() as conn:
        rival_cont = conn.execute(
            "SELECT * FROM contention_log WHERE lock_key=? AND actor=?",
            (lock_key, "clerk"),
        ).fetchall()
        holder_cont = conn.execute(
            "SELECT COUNT(*) c FROM contention_log WHERE lock_key=? AND actor=?",
            (lock_key, "admin"),
        ).fetchone()["c"]
    assert len(rival_cont) == 1
    assert rival_cont[0]["action"] == "争用"
    assert holder_cont == 0
