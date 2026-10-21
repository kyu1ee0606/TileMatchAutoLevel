"""conftest 네트워크 차단·GameBoost 격리 자체 검증 (문서 47 §4 재발 방지).

의도적 차단 시도는 실제 전송 전에 가로채지고(TEST-NET 주소·.invalid 도메인), 확인 후 기록에서 제거한다.
라우트 호출은 미설정 Fake 로만 가므로 시도 0이어야 한다.
"""
import asyncio
import socket

import pytest
from fastapi.testclient import TestClient

import app.api.deps as deps
import app.api.routes.gboost as gb_routes
import app.clients.gboost as gb
from app.main import app

client = TestClient(app)


def _expect_block(network_attempts, fn):
    before = len(network_attempts)
    with pytest.raises(RuntimeError, match="외부 네트워크 차단"):
        fn()
    assert len(network_attempts) == before + 1
    del network_attempts[before:]          # 의도적 시도는 세션 실패 집계에서 제외


def test_transport_layer_blocked(network_attempts):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _expect_block(network_attempts, lambda: s.connect(("192.0.2.1", 443)))
        _expect_block(network_attempts, lambda: s.connect_ex(("192.0.2.1", 443)))
    finally:
        s.close()
    _expect_block(network_attempts, lambda: socket.create_connection(("192.0.2.1", 443)))
    _expect_block(network_attempts, lambda: socket.getaddrinfo("gameboost.example.invalid", 443))
    _expect_block(network_attempts, lambda: gb.aiohttp.ClientSession())


def test_real_gboost_client_never_reachable(network_attempts):
    from tests.conftest import FAKE_CLIENT_CALLS, FAKE_GBOOST
    assert gb.get_gboost_client() is FAKE_GBOOST
    assert deps.get_gboost_client() is FAKE_GBOOST and gb_routes.get_gboost_client() is FAKE_GBOOST
    assert gb._client is FAKE_GBOOST
    assert not isinstance(deps.get_gboost(), gb.GBoostClient)
    n_calls = len(FAKE_CLIENT_CALLS)
    # 쓰기·읽기·health·config·upload-local·thumbnail 경로 전부 → 미설정 응답, 클라이언트 메서드 호출 0
    assert client.get("/api/gboost/health").json()["configured"] is False
    assert client.post("/api/gboost/test_board/test_level", json={"level_json": {"layer": 1}}).status_code == 503
    assert client.get("/api/gboost/test_board/test_level").status_code == 503
    assert client.get("/api/gboost/test_board").status_code == 503
    assert client.delete("/api/gboost/test_board/test_level").status_code == 503
    assert client.post("/api/gboost/upload-local", json={"board_id": "b", "level_ids": ["x"]}).status_code in (503, 422)
    assert client.get("/api/gboost/config").json()["configured"] is False
    assert len(FAKE_CLIENT_CALLS) == n_calls
    assert network_attempts == []
