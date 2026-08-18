"""남은 보스 레벨 초안을 묶음 단위로 끝까지 생성한다(백그라운드용).

UI 버튼과 같은 엔드포인트를 쓰되, 브라우저를 켜두지 않아도 되도록 CLI 로 돈다.
묶음마다 서버가 boss_templates.json 에 즉시 저장하므로 중간에 끊겨도 그때까지는 남는다.
진행 상황은 stdout 으로 흘린다 → nohup 로그로 확인.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "http://localhost:8000/api"
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def load(name):
    return json.loads((ROOT / "data" / name).read_text())


def uncovered():
    T = load("boss_templates.json")
    C = load("boss_concepts.json")
    covered = {int(t["level_min"]) for t in T.values() if isinstance(t, dict)}
    out = []
    for n in range(10, 1501, 10):
        if n in covered:
            continue
        sh = (C.get(str(n)) or {}).get("shape", "").strip()
        if sh:
            out.append((n, sh))
    return out


def post(levels, shapes):
    body = json.dumps({
        "levels": levels, "shapes": shapes, "layer_count": 4, "base": 8,
        "symmetric": True, "max_retry": 2, "vary_layers": False,
    }).encode()
    req = urllib.request.Request(f"{API}/debug/boss-draft-generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=len(levels) * 200 + 120) as r:
        return json.load(r)


def main():
    todo = uncovered()
    print(f"[start] 미커버 {len(todo)}개 · 묶음 {CHUNK} · 예상 {len(todo)*110/60:.0f}분", flush=True)
    t0 = time.time()
    made = failed = 0
    for i in range(0, len(todo), CHUNK):
        part = todo[i:i + CHUNK]
        levels = [n for n, _ in part]
        shapes = {str(n): s for n, s in part}
        t = time.time()
        try:
            r = post(levels, shapes)
        except Exception as ex:  # noqa: BLE001
            # 서버 재시작 시 RemoteDisconnected 처럼 URLError 계열이 아닌 예외도 날아온다.
            # 배치 전체가 죽으면 남은 수십 레벨을 다시 돌려야 하므로 어떤 통신 오류든 삼키고 넘어간다.
            # (완료된 레벨은 서버가 레벨 단위로 이미 저장해 둔 상태다.)
            print(f"[{i+len(part)}/{len(todo)}] Lv{levels[0]}~{levels[-1]} 요청실패: {type(ex).__name__}: {ex}",
                  flush=True)
            failed += len(levels)
            time.sleep(5)          # 서버 재기동 대기
            continue
        made += r["counts"]["made"]
        failed += r["counts"]["failed"]
        el = time.time() - t
        done = i + len(part)
        eta = (time.time() - t0) / done * (len(todo) - done) / 60
        print(f"[{done}/{len(todo)}] Lv{levels[0]}~{levels[-1]} {el:.0f}s "
              f"made={r['counts']['made']} fail={r['counts']['failed']} · 남은 {eta:.0f}분", flush=True)
        for f in r.get("failed", []):
            print(f"    ✗ Lv{f['level']}: {f['reason']}", flush=True)
    print(f"[done] 총 {time.time()-t0:.0f}s · 성공 {made} · 실패 {failed}", flush=True)


if __name__ == "__main__":
    main()
