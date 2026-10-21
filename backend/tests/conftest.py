"""
테스트 세션 전체 외부 네트워크 차단 + GameBoost 클라이언트 격리 (문서 47 §4 재발 방지, 2026-10-20).

배경: 이 머신은 .env 로 GameBoost 실클라이언트가 설정돼 있어 tests/test_api.py 의 gboost 테스트가
실서버(test_board/test_level 저장·썸네일)로 나간 사고가 있었다.

방어 3겹 (pytest_configure = 테스트 모듈 import/수집보다 먼저 설치):
  1) 전송 계층: socket.connect/connect_ex/sendto/create_connection/getaddrinfo 를 가로채
     AF_UNIX·루프백 이름 해석 외에는 즉시 NetworkBlocked + NETWORK_ATTEMPTS 기록.
  2) aiohttp.ClientSession (GameBoost 클라이언트가 쓰는 유일한 HTTP 라이브러리) 을 app.clients.gboost
     모듈에서 차단 클래스로 교체 → 생성 시도 자체를 기록·예외.
  3) GameBoost 클라이언트: 싱글톤·get/update 함수(정의 모듈 + import 해 간 모듈 전부)·FastAPI 의존성을
     미설정 FakeGBoostClient 로 대체. 실 GBoostClient 는 테스트에서 생성되지 않는다.
환경변수/.env/설정 파일은 읽기만 하고 수정하지 않는다.
세션 종료 시 차단된 시도가 1건이라도 있으면 종료 코드를 실패로 바꾼다.
"""
from __future__ import annotations

import socket

import pytest

NETWORK_ATTEMPTS: list = []      # (kind, detail) — 차단된 외부 연결 시도
FAKE_CLIENT_CALLS: list = []     # FakeGBoostClient 메서드 호출 기록

_LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


class NetworkBlocked(RuntimeError):
    pass


def _block(kind: str, detail) -> None:
    NETWORK_ATTEMPTS.append((kind, repr(detail)))
    raise NetworkBlocked(f"테스트 중 외부 네트워크 차단: {kind} {detail!r}")


_orig = {
    "connect": socket.socket.connect,
    "connect_ex": socket.socket.connect_ex,
    "sendto": socket.socket.sendto,
    "create_connection": socket.create_connection,
    "getaddrinfo": socket.getaddrinfo,
}


def _connect(self, address):
    if self.family == getattr(socket, "AF_UNIX", object()):
        return _orig["connect"](self, address)
    _block("socket.connect", address)


def _connect_ex(self, address):
    if self.family == getattr(socket, "AF_UNIX", object()):
        return _orig["connect_ex"](self, address)
    _block("socket.connect_ex", address)


def _sendto(self, *args):
    if self.family == getattr(socket, "AF_UNIX", object()):
        return _orig["sendto"](self, *args)
    _block("socket.sendto", args[-1] if args else None)


def _create_connection(address, *a, **k):
    _block("socket.create_connection", address)


def _getaddrinfo(host, *a, **k):
    h = host.decode() if isinstance(host, bytes) else host
    if h in _LOCAL_HOSTS:
        return _orig["getaddrinfo"](host, *a, **k)
    _block("socket.getaddrinfo", h)


class _BlockedClientSession:
    """aiohttp.ClientSession 대체 — 생성 자체를 차단."""

    def __init__(self, *a, **k):
        _block("aiohttp.ClientSession", k.get("base_url"))


class FakeGBoostClient:
    """미설정 GameBoost 클라이언트. 라우트는 is_configured=False 로 503/미설정 응답을 낸다.
    어떤 메서드든 호출되면 기록 후 예외(네트워크 없음)."""

    base_url = ""
    api_key = ""
    project_id = ""
    is_configured = False

    def __getattr__(self, name):
        def _call(*a, **k):
            FAKE_CLIENT_CALLS.append(name)
            raise NetworkBlocked(f"FakeGBoostClient.{name} 호출 차단")
        return _call


FAKE_GBOOST = FakeGBoostClient()


def _fake_get():
    return FAKE_GBOOST


def _fake_update(base_url: str, api_key: str, project_id: str):
    FAKE_CLIENT_CALLS.append("update_gboost_client")
    return FAKE_GBOOST


def pytest_configure(config):
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.socket.sendto = _sendto
    socket.create_connection = _create_connection
    socket.getaddrinfo = _getaddrinfo

    import app.clients as clients_pkg
    import app.clients.gboost as gb
    import app.api.deps as deps
    import app.api.routes.gboost as gb_routes
    from app.main import app

    gb.aiohttp.ClientSession = _BlockedClientSession  # gb 모듈이 보는 aiohttp 모듈 속성
    gb._client = FAKE_GBOOST
    for mod in (gb, clients_pkg, deps, gb_routes):
        if hasattr(mod, "get_gboost_client"):
            mod.get_gboost_client = _fake_get
        if hasattr(mod, "update_gboost_client"):
            mod.update_gboost_client = _fake_update
    app.dependency_overrides[deps.get_gboost] = _fake_get


@pytest.fixture
def network_attempts():
    return NETWORK_ATTEMPTS


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    terminalreporter.write_line(
        f"[network-guard] 차단된 외부 연결 시도 {len(NETWORK_ATTEMPTS)}건, "
        f"FakeGBoostClient 호출 {len(FAKE_CLIENT_CALLS)}건 {NETWORK_ATTEMPTS[:5]}")


def pytest_sessionfinish(session, exitstatus):
    if NETWORK_ATTEMPTS:
        session.exitstatus = 1
