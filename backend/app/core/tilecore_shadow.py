"""TILECORE shadow adapter — run the C# FastJudge next to the Python A* solver and log differences.

Plan: claudedocs/PLAN_CSHARP_ACCELERATION_20261102.md §0-A (C# -> shadow -> parity -> speed -> on).

Switch = environment variable ``TILECORE``:
  * unset / ``off`` (default): nothing here runs. ``solver.solve_level`` returns the Python result untouched.
  * ``shadow``: Python result is still the service result. After it, the same level is judged by FastJudge
    (C#, fengine rules, NOT BotSimulator rules) and one JSONL line is appended to the shadow log.
    Every C# failure (missing binary, crash, timeout, unsupported gimmick) is logged, never raised.
  * ``on``: not allowed yet for the solver (rule sets differ, gate §0-A not passed) -> treated as ``shadow``.

Other environment variables (all optional):
  TILECORE_FASTJUDGE_DLL   FastJudge.dll path (default: ~/tilecore/vendor/fastjudge_snap_20261102/bin/FastJudge.dll)
  TILECORE_DOTNET          dotnet executable (default: "dotnet" on PATH)
  TILECORE_SHADOW_LOG      JSONL output (default: ~/tilecore/shadow/solver_shadow_diff.jsonl)
  TILECORE_RULES           FastJudge --rules game|ref (default game)
  TILECORE_SHADOW_NODE_CAP "same" (= Python node_budget, default) | integer (0 = no node cap)
  TILECORE_SHADOW_MEM_MB   FastJudge --max-mem-mb (default 400)
  TILECORE_SHADOW_T0       "1" (default) compare the t0 layout of BotSimulator vs FastJudge, "0" skip

Known rule differences between the two engines are listed in /tmp/ingame_port/agent_diff/DIFF.md; the
log line carries ``diff_hints`` (gimmicks present that hit a DIFF.md row) so mismatches can be classified.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_DLL = os.path.expanduser("~/tilecore/vendor/fastjudge_snap_20261102/bin/FastJudge.dll")
_DEFAULT_LOG = os.path.expanduser("~/tilecore/shadow/solver_shadow_diff.jsonl")
_LOG_LOCK = threading.Lock()

# DIFF.md rows that make BotSimulator (solver.py) and fengine (FastJudge) disagree, keyed by gimmick base name.
_DIFF_HINTS = {
    "stack": "#4 stack cover (BS without par: stack top blocked by upper layers)",
    "craft": "#5 craft emit / #17",
    "bomb": "#6 bomb (BS clamps count 3-5 without effect_parse par)",
    "ice": "#7 ice fail check / link-pair melt",
    "curtain": "#8b curtain special rules",
    "grass": "#9 grass near identity (BS without par)",
    "link": "#6/#7/#8 link-pair side effects",
    "key": "#12 key lock init",
    "frog": "#14 frog (FastJudge unsupported)",
    "teleport": "#15 teleporter (FastJudge unsupported)",
}


def mode() -> str:
    """off | shadow. Unknown values and ``on`` never change the service result."""
    v = (os.environ.get("TILECORE") or "off").strip().lower()
    if v in ("shadow", "on"):
        return "shadow"
    return "off"


# ───────────────────────── conversion ─────────────────────────

def _layer_count(level_json: Dict[str, Any]) -> int:
    try:
        return int(level_json.get("layer", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _effective_use_tile_count(level_json: Dict[str, Any]) -> int:
    """Same value BotSimulator._create_initial_state feeds its t0 distributor."""
    from .bot_simulator import BotSimulator
    try:
        u = int(level_json.get("useTileCount", BotSimulator.DEFAULT_USE_TILE_COUNT) or 0)
    except (TypeError, ValueError):
        u = BotSimulator.DEFAULT_USE_TILE_COUNT
    if u <= 0:
        u = BotSimulator.DEFAULT_USE_TILE_COUNT
    return min(u, BotSimulator.MAX_USE_TILE_COUNT)


def to_fastjudge_row(level_json: Dict[str, Any], level_id: str = "maptool") -> Dict[str, Any]:
    """Map-tool level_json -> FastJudge row ({"id","map",randSeed,useTileCount,...}). Pure (no mutation)."""
    layers: Dict[str, Any] = {}
    for i in range(_layer_count(level_json)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict):
            continue
        out: Dict[str, Any] = {}
        if ld.get("col") is not None:
            out["col"] = ld.get("col")
        if isinstance(ld.get("tiles"), dict):
            out["tiles"] = ld["tiles"]
        layers[f"layer_{i}"] = out

    def first(*keys, default=0):
        for k in keys:
            if level_json.get(k) not in (None, ""):
                return level_json.get(k)
        return default

    return {
        "id": level_id,
        "map": layers,
        "randSeed": first("randSeed", "seed"),
        "useTileCount": _effective_use_tile_count(level_json),
        "unlockTile": first("unlockTile", "xUnlockTile"),
        # BotSimulator reads xShuffleTile / xTypeImbalance (0-10); FastJudge reads shuffleTile / typeImbalance (/10).
        "shuffleTile": first("xShuffleTile", "shuffleTile"),
        "typeImbalance": first("xTypeImbalance", "typeImbalance"),
        "timea": first("timeAttack", "timea"),
    }


def level_hash(level_json: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(level_json, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def gimmick_set(level_json: Dict[str, Any]) -> List[str]:
    g = set()
    for i in range(_layer_count(level_json)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td):
                continue
            if isinstance(td[0], str) and (td[0].startswith("stack") or td[0].startswith("craft")):
                g.add(td[0][:5])
            if isinstance(td[0], str) and td[0].lower() in ("key", "t16"):
                g.add("key")
            if len(td) > 1 and isinstance(td[1], str) and td[1] and td[1] != "0":
                g.add(td[1].split("_")[0].lower())
    return sorted(g)


def bs_concrete_types(level_json: Dict[str, Any]) -> Dict[str, str]:
    """BotSimulator initial-state tile type per cell. Keys: "L_x_y" (normal), "L_x_y_k" (stack/craft inner k, 0 = bottom)."""
    from .bot_simulator import BotSimulator
    lvl = dict(level_json)
    lvl["max_moves"] = 9999
    st = BotSimulator()._create_initial_state(lvl, 9999)
    out: Dict[str, str] = {}
    tiles = [t for layer in st.tiles.values() for t in layer.values()]
    tiles += list((getattr(st, "stacked_tiles", None) or {}).values())
    for t in tiles:
        if t.is_stack_tile or t.is_craft_tile:
            out[t.original_full_key] = t.tile_type      # craft tile already emitted to its spawn cell keeps its box key
        else:
            out[f"{t.layer_idx}_{t.x_idx}_{t.y_idx}"] = t.tile_type
    return out


def _has_t0(level_json: Dict[str, Any]) -> bool:
    for i in range(_layer_count(level_json)):
        ld = level_json.get(f"layer_{i}")
        for td in (ld.get("tiles") or {}).values() if isinstance(ld, dict) and isinstance(ld.get("tiles"), dict) else ():
            if isinstance(td, list) and td and (td[0] == "t0" or (isinstance(td[0], str) and td[0][:5] in ("stack", "craft"))):
                return True
    return False


def bs_baked_level(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of level_json with every t0 (board and stack/craft inner) replaced by BotSimulator's own assignment.

    Used only when randSeed is 0: the game lays such t0 out from the clock (not reproducible) and FastJudge refuses,
    while BotSimulator still picks a layout. Baking it lets the shadow compare the RULES on the same concrete board.
    """
    import copy
    types = bs_concrete_types(level_json)
    out = copy.deepcopy(level_json)
    for i in range(_layer_count(out)):
        ld = out.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for pos, td in ld["tiles"].items():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            if td[0][:5] in ("stack", "craft"):
                inner, k = [], 0
                while f"{i}_{pos}_{k}" in types:
                    inner.append(types[f"{i}_{pos}_{k}"])
                    k += 1
                if inner:
                    while len(td) < 3:
                        td.append([])
                    td[2] = [len(inner), "_".join(inner)]
            elif td[0] == "t0" and f"{i}_{pos}" in types:
                td[0] = types[f"{i}_{pos}"]
    return out


# ───────────────────────── FastJudge process ─────────────────────────

def _dll() -> str:
    return os.environ.get("TILECORE_FASTJUDGE_DLL") or _DEFAULT_DLL


def run_fastjudge(cmd: str, rows: List[Tuple[str, Dict[str, Any]]], extra: List[str], timeout_s: float) -> Dict[str, Any]:
    """Run ``FastJudge <cmd> --variants <tmp> --out <tmp>``. Returns {"ok", "out_text", "wall_s", "error"}."""
    dll = _dll()
    if not os.path.exists(dll):
        return {"ok": False, "error": f"fastjudge_missing:{dll}", "wall_s": 0.0}
    dotnet = os.environ.get("TILECORE_DOTNET") or "dotnet"
    rules = (os.environ.get("TILECORE_RULES") or "game").strip()
    with tempfile.TemporaryDirectory(prefix="tilecore_") as td:
        vin = os.path.join(td, "v.jsonl")
        out = os.path.join(td, "out")
        with open(vin, "w", encoding="utf-8") as f:
            for rid, row in rows:
                f.write(json.dumps({"id": rid, "step": 0, "index": None, "seed": None, "ok": True, "row": row},
                                   ensure_ascii=False) + "\n")
        argv = [dotnet, dll, cmd, "--variants", vin, "--out", out, "--rules", rules] + extra
        t0 = time.perf_counter()
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout_{timeout_s:.0f}s", "wall_s": time.perf_counter() - t0}
        except OSError as exc:
            return {"ok": False, "error": f"spawn:{exc}", "wall_s": time.perf_counter() - t0}
        wall = time.perf_counter() - t0
        if p.returncode != 0 or not os.path.exists(out):
            return {"ok": False, "error": f"exit_{p.returncode}:{(p.stderr or '')[-300:]}", "wall_s": wall}
        with open(out, encoding="utf-8") as f:
            return {"ok": True, "out_text": f.read(), "wall_s": wall, "error": None}


def _parse_judge_csv(text: str) -> Optional[Dict[str, str]]:
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows[0] if rows else None


def fastjudge_solve(level_json: Dict[str, Any], node_budget: int, time_budget_s: float) -> Dict[str, Any]:
    cap_env = (os.environ.get("TILECORE_SHADOW_NODE_CAP") or "same").strip().lower()
    node_cap = int(node_budget) if cap_env == "same" else int(cap_env)
    budget = float(time_budget_s) if time_budget_s and time_budget_s > 0 else 600.0
    mem = os.environ.get("TILECORE_SHADOW_MEM_MB") or "400"
    extra = ["--procs", "1", "--budgets", repr(budget), "--max-nodes", str(node_cap), "--max-mem-mb", mem]
    src = level_json
    t0_source = "fastjudge_game_t0"
    try:
        seed = int(level_json.get("randSeed", level_json.get("seed", 0)) or 0)
    except (TypeError, ValueError):
        seed = 0
    if seed == 0 and _has_t0(level_json) and (os.environ.get("TILECORE_SHADOW_SEED0") or "bs") == "bs":
        src = bs_baked_level(level_json)
        t0_source = "bs_baked_seed0"
    r = run_fastjudge("judge", [("maptool", to_fastjudge_row(src))], extra, timeout_s=budget + 30.0)
    res: Dict[str, Any] = {"wall_s": round(r["wall_s"], 4), "node_cap": node_cap, "budget_s": budget, "t0_source": t0_source}
    if not r["ok"]:
        res.update(verdict="CS_ERROR", reason=r["error"])
        return res
    row = _parse_judge_csv(r["out_text"]) or {}
    res.update(verdict=row.get("verdict", "CS_ERROR"), reason=row.get("reason", ""), nodes=row.get("nodes", ""),
               sec=row.get("sec", ""), tag=row.get("judge", ""))
    return res


def t0_parity(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """Compare the concrete tile type per cell: BotSimulator initial state vs FastJudge t0 bake."""
    from .solver import is_key_tile
    r = run_fastjudge("t0", [("maptool", to_fastjudge_row(level_json))], [], timeout_s=60.0)
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    line = (r["out_text"] or "").strip().splitlines()
    cells = json.loads(line[0]).get("cells") if line else None
    if not isinstance(cells, dict):
        return {"ok": False, "error": f"t0_cells:{cells}"}
    cs: Dict[str, str] = {}
    for k, v in cells.items():          # "L_x_y" -> type | [inner types bottom->top]
        if isinstance(v, list):
            for idx, t in enumerate(v):
                cs[f"{k}_{idx}"] = "t16" if str(t).lower() in ("key", "t16") else t
        else:
            cs[k] = v
    bs = {k: ("t16" if is_key_tile(t, "") else t) for k, t in bs_concrete_types(level_json).items()}
    common = sorted(set(cs) & set(bs))
    mism = [k for k in common if cs[k] != bs[k]]
    return {"ok": True, "compared": len(common), "cs_only": len(set(cs) - set(bs)), "bs_only": len(set(bs) - set(cs)),
            "mismatch": len(mism), "first": [(k, bs[k], cs[k]) for k in mism[:5]], "wall_s": round(r["wall_s"], 4)}


# ───────────────────────── classification / log ─────────────────────────

_PY2CS = {"PROVEN_SOLVABLE": "PATH", "PROVEN_IMPOSSIBLE": "IMPOSSIBLE", "UNCERTAIN": "UNKNOWN"}


def classify(py_verdict: str, cs_verdict: str, cs_reason: str = "") -> str:
    if cs_verdict == "CS_ERROR":
        return "cs_error"
    if cs_verdict == "UNKNOWN" and cs_reason.startswith("unsupported"):
        return "cs_unsupported"
    if cs_verdict == "UNKNOWN" and cs_reason.startswith("error:"):
        # randSeed 0 + t0 tiles = time-based layout in the game -> FastJudge refuses (not a mismatch)
        return "cs_unsupported_seed0" if "randSeed 0" in cs_reason else "cs_error"
    p = _PY2CS.get(py_verdict, "?")
    if p == cs_verdict:
        return "same"
    if p == "UNKNOWN":
        return "py_uncertain_cs_decided"      # allowed direction (gate ②), listed
    if cs_verdict == "UNKNOWN":
        return "py_decided_cs_unknown"
    return "contradiction"                     # PATH vs IMPOSSIBLE -> rule diff / t0 diff / bug


def _append(line: Dict[str, Any]) -> None:
    path = os.environ.get("TILECORE_SHADOW_LOG") or _DEFAULT_LOG
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = (json.dumps(line, ensure_ascii=False, default=str) + "\n").encode("utf-8")
    with _LOG_LOCK:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def shadow_solve(level_json: Dict[str, Any], py_result: Dict[str, Any], py_elapsed_s: float,
                 node_budget: int, time_budget_s: float) -> Optional[Dict[str, Any]]:
    """Judge the same level with FastJudge and log. Never raises, never mutates its arguments."""
    try:
        gims = gimmick_set(level_json)
        cs = fastjudge_solve(level_json, node_budget, time_budget_s)
        line: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "kind": "solve_level",
            "input_hash": level_hash(level_json),
            "node_budget": node_budget, "time_budget_s": time_budget_s,
            "py": {"verdict": py_result.get("verdict"), "nodes": py_result.get("nodes_expanded"),
                   "moves": py_result.get("moves_to_clear"), "sec": round(py_elapsed_s, 4),
                   "div3": bool(py_result.get("divisibility_violation")),
                   "downgraded": py_result.get("unsupported_gimmicks"),
                   "reason": (py_result.get("reason") or "")[:160]},
            "cs": cs,
            "category": classify(py_result.get("verdict", ""), cs.get("verdict", ""), cs.get("reason", "")),
            "gimmicks": gims,
            "diff_hints": [_DIFF_HINTS[g] for g in gims if g in _DIFF_HINTS],
        }
        if cs.get("t0_source") == "bs_baked_seed0":
            line["t0"] = {"ok": True, "skipped": "bs_baked_seed0 (same layout by construction)"}
        elif line["category"] not in ("same",) and (os.environ.get("TILECORE_SHADOW_T0") or "1") != "0":
            try:
                line["t0"] = t0_parity(level_json)
            except Exception as exc:  # noqa: BLE001
                line["t0"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        _append(line)
        return line
    except Exception as exc:  # noqa: BLE001 — shadow must never affect the service
        try:
            _append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "solve_level", "category": "shadow_internal_error",
                     "error": f"{type(exc).__name__}: {exc}"[:300]})
        except Exception:  # noqa: BLE001
            pass
        return None
