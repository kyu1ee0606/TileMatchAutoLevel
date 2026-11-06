"""스레드풀 동시 실행(def 라우트) 하에서의 공유 상태 경쟁 회귀 테스트 (리뷰 review_backend_opt_20261106).

모든 파일 경로는 tmp 로 돌린다. 경쟁은 느린 단계를 주입(sleep)해 결정적으로 재현한다.
"""
import json
import os
import random
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import production_store as PS
from app.api.routes import analyze as AN
from app.core import turtle_bases as TB


@pytest.fixture()
def client():
    return TestClient(app)


# ── 1. production_store: 오래된 base_version 은 반드시 409 ───────────────────
@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(PS, "_INDEX_PATH", str(tmp_path / "_index.json"))
    return tmp_path


def _put(client, bid, base, n=1):
    body = {"batch_id": bid, "batch": {"name": "x"}, "levels": [], "base_version": base}
    return client.put(f"/api/production/batches/{bid}", json=body)


def test_stale_index_does_not_bypass_409(client, store):
    """인덱스에 (mtime,size) 일치 + 잘못된 버전(v2)이 있어도 실제 파일 v3 기준으로 409."""
    assert _put(client, "b1", None).json()["version"] == 1
    assert _put(client, "b1", 1).json()["version"] == 2
    assert _put(client, "b1", 2).json()["version"] == 3
    fp = store / "b1.json"
    st = os.stat(fp)
    idx = json.load(open(store / "_index.json"))
    idx["b1"].update(version=2, _mtime=st.st_mtime, size_bytes=st.st_size)  # 경쟁으로 잘못 결합된 상태
    json.dump(idx, open(store / "_index.json", "w"))
    r = _put(client, "b1", 2)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["server_version"] == 3


def test_concurrent_put_same_base_only_one_wins(client, store, monkeypatch):
    assert _put(client, "b2", None).status_code == 200
    # 검사~쓰기 사이를 넓혀 경쟁 유도
    orig = PS._enforce_rule_gate

    def slow(levels):
        time.sleep(0.15)
        return orig(levels)
    monkeypatch.setattr(PS, "_enforce_rule_gate", slow)
    res = []
    ts = [threading.Thread(target=lambda: res.append(_put(client, "b2", 1).status_code)) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(res) == [200, 409, 409, 409], res


# ── 2. turtle_bases: 측정 저장이 타 항목 변경을 유실하면 안 됨 ──────────────
def test_turtle_set_difficulty_vs_put_no_lost_update(tmp_path, monkeypatch):
    monkeypatch.setattr(TB, "STORE_PATH", str(tmp_path / "tb.json"))
    TB._save({"a": {"name": "A", "grid": 8, "cells": ["0_0"]}})
    orig_save = TB._save

    def slow_save(d):
        if threading.current_thread().name == "A":
            time.sleep(0.3)
        orig_save(d)
    monkeypatch.setattr(TB, "_save", slow_save)
    ta = threading.Thread(name="A", target=lambda: TB.set_difficulty("a", {"coef": 0.5}))
    ta.start(); time.sleep(0.1)
    tbt = threading.Thread(name="B", target=lambda: TB.put_base("b", "B", 8, ["1_1"]))
    tbt.start(); ta.join(); tbt.join()
    d = TB._load()
    assert "b" in d, "put_base 변경이 측정 저장에 덮여 유실"
    assert d["a"].get("difficulty") == {"coef": 0.5}


def test_turtle_set_difficulty_vs_delete_no_resurrect(tmp_path, monkeypatch):
    monkeypatch.setattr(TB, "STORE_PATH", str(tmp_path / "tb.json"))
    TB._save({"a": {"name": "A", "grid": 8, "cells": ["0_0"]}, "c": {"name": "C", "grid": 8, "cells": ["2_2"]}})
    orig_save = TB._save

    def slow_save(d):
        if threading.current_thread().name == "A":
            time.sleep(0.3)
        orig_save(d)
    monkeypatch.setattr(TB, "_save", slow_save)
    ta = threading.Thread(name="A", target=lambda: TB.set_difficulty("a", {"coef": 0.5}))
    ta.start(); time.sleep(0.1)
    tbt = threading.Thread(name="B", target=lambda: TB.delete_base("c"))
    tbt.start(); ta.join(); tbt.join()
    assert "c" not in TB._load(), "삭제된 항목이 부활"


# ── 3. 보스 생성: 동시 요청에도 같은 seed → 같은 결과 ─────────────────────
def _boss_req(seed):
    pos = [f"{x}_{y}" for x in range(2, 6) for y in range(2, 6)]
    return AN.BossTemplateGenerateRequest(
        level_number=900, random_seed=seed, apply_gimmicks=True, gimmick_intensity=1.0,
        use_tile_count_override=6,
        layers=[AN.BossTemplateLayer(layer=0, col=8, row=8, positions=pos,
                                     gimmicks={p: "bomb" for p in pos[:6]})])


def _run_boss(seed):
    # generate_from_boss_template 는 async def(이벤트 루프 직렬화). 스레드별 루프로 호출해도
    # 본문 안의 _BOSS_GEN_LOCK 이 보스 요청끼리 직렬화해야 한다.
    import asyncio
    return asyncio.run(AN.generate_from_boss_template(_boss_req(seed)))


def test_boss_generate_seed_deterministic_under_concurrency(monkeypatch):
    seeds = [11, 22, 33, 44]
    base = {s: json.dumps(_run_boss(s), sort_keys=True, default=str) for s in seeds}
    assert len(set(base.values())) > 1, "seed 마다 결과가 달라야 테스트가 의미 있음"
    def _slow(orig):
        def f(*a, **k):
            time.sleep(0.003)  # GIL 양보 → 다른 스레드의 seed()/난수 소비와 교차
            return orig(*a, **k)
        return f
    for name in ("randint", "random", "choice", "shuffle", "sample", "randrange"):
        monkeypatch.setattr(random, name, _slow(getattr(random, name)))
    out = {}

    def run(s, i):
        out[(s, i)] = json.dumps(_run_boss(s), sort_keys=True, default=str)
    ts = [threading.Thread(target=run, args=(s, i)) for s in seeds for i in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    bad = [k for k, v in out.items() if v != base[k[0]]]
    assert not bad, f"동시 요청에서 seed 결과 변형: {bad}"


# ── 4. 템플릿 측정: 측정 중 모양이 바뀌면 점수 저장 금지 ───────────────────
def test_template_measure_discards_when_shape_changed(client, tmp_path, monkeypatch):
    path = str(tmp_path / "level_templates.json")
    monkeypatch.setattr(AN, "LEVEL_TEMPLATES_PATH", path)
    AN._LT_CACHE["sig"] = None
    lj_old = {"layer": 1, "layer_0": {"col": "8", "row": "8", "tiles": {"0_0": ["t1", ""]}, "num": "1"}}
    lj_new = {"layer": 1, "layer_0": {"col": "8", "row": "8", "tiles": {"1_1": ["t2", ""]}, "num": "1"}}
    AN._save_level_templates({"templates": {"T": {"name": "T", "level_json": lj_old}}})

    class R:
        autoplay_score = 77.0; static_score = 50.0; static_grade = "B"; autoplay_grade = "B"; bot_stats = []

    def fake_autoplay(req, analyzer):
        # 측정 중 다른 요청이 모양 편집
        d = AN._load_level_templates()
        d["templates"]["T"]["level_json"] = lj_new
        AN._save_level_templates(d)
        return R()
    monkeypatch.setattr(AN, "analyze_autoplay", fake_autoplay)
    resp = AN.debug_level_template_measure("T", 10)
    saved = AN._load_level_templates()["templates"]["T"]
    assert saved["level_json"] == lj_new
    assert "measured_difficulty" not in saved, f"옛 모양 점수가 새 모양에 저장됨: {resp}"
    assert resp.get("error") == "template_changed"


def test_template_measure_saves_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(AN, "LEVEL_TEMPLATES_PATH", str(tmp_path / "lt.json"))
    AN._LT_CACHE["sig"] = None
    lj = {"layer": 1, "layer_0": {"col": "8", "row": "8", "tiles": {"0_0": ["t1", ""]}, "num": "1"}}
    AN._save_level_templates({"templates": {"T": {"name": "T", "level_json": lj}}})

    class R:
        autoplay_score = 77.0; static_score = 50.0; static_grade = "B"; autoplay_grade = "B"; bot_stats = []
    monkeypatch.setattr(AN, "analyze_autoplay", lambda req, an: R())
    resp = AN.debug_level_template_measure("T", 10)
    assert resp.get("measured") is True
    assert AN._load_level_templates()["templates"]["T"]["measured_difficulty"] == 0.77
