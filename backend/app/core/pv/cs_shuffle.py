"""Bit-exact Python reference port of the game client's t0 tile distribution.

Source of truth (game repo, read-only):
  /Users/casualdev/sp_meowsgarden  (DB_Level.cs last commit b741f6a3, 2026-09-21)
  - Assets/00.spComponents/zWellRandom.cs                         (ZW)
  - Assets/00.spComponents/spInteger.cs                           (SI)
  - Assets/00.spComponents/spEncrypt/spEncryptValue.cs            (SE)  AsInt/AsLong
  - Assets/08.Scripts/Tile_Script/InGame/DB_Level.cs              (CS)
      CTileStackInfo ctor / GetTileIDArr        CS:149-212
      CTile.isKeyTile / GetTileIDNum            CS:230-234, 257-271
      CTileList ctor                            CS:385-424
      CLayerList ctor                           CS:520-557
      CLevel.GetEmptyTileList                   CS:870-945
      CLevelList.GetToAddIndexList              CS:1123-1156
      CLevelList.ShuffleEmptyTiles              CS:1167-1292
      CLevelList.ApplyVisualTileRemap           CS:1307-1354 (optional, see below)
      CLevelList.DistributeTiles                CS:1356-1502

Written from the C# text only (04_seed_variant_plan.md §A3, P0 E-P0-1).
Every step carries the C# line it mirrors.  Do NOT "fix" behaviour here to
match editor ports (tileDistributor.ts / bot_simulator.TileDistributor) —
the client is the reference.

Scope / deliberate limits
- Input is the level *map* object exactly as the client parses it (layer and
  tile key ORDER matters: CS:880-903 iterates `layer_{i}` by number and tiles in
  JSON key insertion order).  Python dicts from json.loads keep that order and
  resolve duplicate keys like SimpleJSON (first position, last value).
- randSeed 0 is time based on the client (ZW:25-30) -> not reproducible ->
  PvContractError.  Negative seeds are reproduced via the (uint) cast (CS:1171).
- useTileCount <= 0 makes the client read the tile-skin count
  (CS:865-868, 1190-1193); that table is not ported -> caller must pass
  `skin_tile_count`, else PvUnsupportedInput.
- Situations where the client would throw (NRE / IndexOutOfRange) raise
  CsClientCrash so they are never mistaken for a valid board.
- Visual remap (CS:1289-1354) runs after the logical distribution with its own
  RNG and is skipped for every current skin (icon_order, CS:1312).  It is NOT
  applied by default; `apply_visual_tile_remap` is provided for golden checks.
- Logical result only: hashes (structHash/typesHash) live in pv/canonical.py.
"""
from __future__ import annotations

import copy
import json
import math
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

U32 = 0xFFFFFFFF


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────
class PvError(Exception):
    """Base error for the PV reference port."""


class CsClientCrash(PvError):
    """The client would throw on this input (NRE / index out of range / overflow)."""


class PvContractError(PvError):
    """Client runs, but the result is forbidden by the PV contract
    (time-based seed, per-type count not divisible by 3, ...)."""


class PvUnsupportedInput(PvError):
    """Input shape whose client semantics are not ported / not verified."""


# ─────────────────────────────────────────────────────────────────────────────
# Integer helpers (C# unchecked int / uint semantics)
# ─────────────────────────────────────────────────────────────────────────────
def to_u32(v: int) -> int:
    return v & U32


def to_i32(v: int) -> int:
    v &= U32
    return v - 0x1_0000_0000 if v & 0x8000_0000 else v


def f32(x: float) -> float:
    """Round a Python float (double) to IEEE float32."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def round_to_int_unity(x: float) -> int:
    """Mathf.RoundToInt(float f) == (int)Math.Round(f): banker's rounding."""
    return to_i32(int(round(x)))  # Python round() is round-half-to-even


# ─────────────────────────────────────────────────────────────────────────────
# zWellRandom (ZW:1-85) — WELL512
# ─────────────────────────────────────────────────────────────────────────────
class ZWellRandom:
    WELL512_STATE_SIZE = 16  # ZW:5

    def __init__(self, seed: int):
        self._state = [0] * self.WELL512_STATE_SIZE  # ZW:7
        self._index = 0
        self.cur_seed = 0
        self.calls = 0  # number of _rand() calls (diagnostic, not in C#)
        self.seed(seed)

    def seed(self, seed: int) -> None:  # ZW:21-42
        seed = to_u32(seed)
        if seed == 0:
            # ZW:25-30: seed 0 -> DateTime.Now based (seconds). Not reproducible.
            raise PvContractError("zWellRandom seed 0 is time-based on the client (ZW:25-30)")
        self._state[0] = seed  # ZW:32
        for i in range(1, self.WELL512_STATE_SIZE):  # ZW:33-37
            prev = self._state[i - 1]
            # (uint)(1812433253 * (prev ^ (prev >> 30)) + i): int*uint -> long, no overflow, then truncate
            self._state[i] = to_u32(1812433253 * (prev ^ (prev >> 30)) + i)
        self._index = 0  # ZW:39
        self.cur_seed = seed  # ZW:41

    @staticmethod
    def _mat0(v: int, t: int) -> int:  # ZW:44-47
        return to_u32(v ^ (v << t))

    def _rand(self) -> int:  # ZW:50-69
        self.calls += 1
        st = self._state
        idx = self._index
        a = st[idx]  # ZW:54
        c = st[(idx + 13) & 15]  # ZW:55
        b = to_u32(a ^ c ^ (a << 16) ^ (c << 15))  # ZW:57
        c = st[(idx + 9) & 15]  # ZW:59
        c ^= c >> 11  # ZW:60
        a = to_u32(b ^ c)
        st[idx] = a  # ZW:62
        idx = (idx + 15) & 15  # ZW:63
        self._index = idx
        z0 = st[idx]  # ZW:64
        st[idx] = to_u32(  # ZW:65-66
            self._mat0(z0, 2) ^ self._mat0(b, 18) ^ (c << 28) ^ (a ^ ((a << 5) & 0xDA442D24))
        )
        return st[idx]  # ZW:68

    def rand(self, s: int, e: int = -999999) -> int:  # ZW:72-84
        if e == -999999:  # ZW:74-78 (one-arg form: [0, s-1])
            e = s - 1
            s = 0
        e = to_i32(e - s + 1)  # ZW:80
        if e == 0:
            return 0  # ZW:81 — no RNG consumption
        return to_i32(s + to_i32(self._rand() % to_u32(e)))  # ZW:83


# ─────────────────────────────────────────────────────────────────────────────
# spInteger.Parse (SI:9-35) and spEncrypt.AsInt (SE:600-603 -> AsLong SE:520-545)
# ─────────────────────────────────────────────────────────────────────────────
def sp_integer_parse(num: Optional[str]) -> int:
    """SI:9-35 — strip non-digits; first '-' anywhere flips sign; '.' after a digit stops."""
    if num is None or num == "":
        return 0
    result = 0
    sign = 1
    digit = 0
    for ch in num:
        if digit > 0 and ch == ".":
            break
        if "0" <= ch <= "9":
            result = to_i32(result * 10 + (ord(ch) - 48))
            digit += 1
        elif unicodedata.category(ch) == "Nd":
            # char.IsDigit accepts non-ASCII Nd digits with (c - '0') arithmetic; not ported.
            raise PvUnsupportedInput(f"non-ASCII digit in tile id: {num!r}")
        elif ch == "-" and sign == 1:
            sign = -1
    return to_i32(result * sign)


# C# double.TryParse(s, NumberStyles.Float, InvariantCulture):
#   leading/trailing white (U+0009..U+000D, U+0020), leading sign, decimal point, exponent.
_CS_FLOAT_RE = re.compile(r"^[\t\n\v\f\r ]*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[\t\n\v\f\r ]*$")
_CS_SPECIAL_RE = re.compile(r"^\s*[+-]?(?:infinity|nan|∞)\s*$", re.IGNORECASE)


def as_int(v: Any) -> int:
    """`jsonNode.AsEncrypt.AsInt` for the JSON value kinds that occur in level rows.

    - missing / null  -> base JSONNode.AsEncrypt = new spEncrypt() -> 0 (assumed, see report)
    - string          -> double.TryParse(Float, Invariant) ? (int)(long)v : 0   (SE:529-535, 600-603)
    - number          -> JSONNumber.AsEncrypt: integral -> spInt, else spDouble; AsInt = (int)(long)v
    """
    if v is None:
        return 0
    if isinstance(v, bool):
        raise PvUnsupportedInput("bool AsInt not ported")
    if isinstance(v, int):
        if abs(v) >= 2**53:
            raise PvUnsupportedInput(f"integer beyond double precision: {v}")
        return to_i32(v)  # (int)(long)(double)v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v) or abs(v) >= 2**63:
            raise PvUnsupportedInput(f"non-finite / out-of-long number: {v}")
        return to_i32(int(v))  # (long) truncates toward zero, (int) keeps low 32 bits
    if isinstance(v, str):
        if _CS_SPECIAL_RE.match(v):
            raise PvUnsupportedInput(f"special double literal: {v!r}")
        if not _CS_FLOAT_RE.match(v):
            return 0  # TryParse failed -> 0L (SE:532-533)
        d = float(v.strip("\t\n\v\f\r "))
        if math.isinf(d) or abs(d) >= 2**63:
            raise PvUnsupportedInput(f"out-of-long number string: {v!r}")
        return to_i32(int(d))
    raise PvUnsupportedInput(f"AsInt of {type(v).__name__} not ported")


def _as_string(v: Any, what: str) -> str:
    """AsEncrypt.AsString for the node kinds we accept (strings; null -> "")."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    raise PvUnsupportedInput(f"{what}: AsString of {type(v).__name__} not ported")


# ─────────────────────────────────────────────────────────────────────────────
# Map model (CTile / CTileStackInfo / CTileList / CLayerList)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(eq=False)
class CTile:
    layer_name: str
    pos: str
    tile_id: str  # xTileID.AsString (mutated by the shuffle)
    effect: str  # xEffect.AsString
    inner_index: Optional[int] = None  # None = board tile; else index in stackCTileList (0 = bottom)
    stack: Optional[List["CTile"]] = None  # xTileStackInfo.stackCTileList (None = no stack info)

    @property
    def is_key_tile(self) -> bool:  # CS:234 (ToLower: ASCII assumed)
        return self.tile_id == "t16" or self.tile_id.lower() == "key" or self.effect.lower() == "key"

    @property
    def tile_id_num(self) -> int:  # CS:257-271
        if self.is_key_tile:
            return 16
        if self.tile_id.startswith("t"):
            return sp_integer_parse(self.tile_id)
        return -1


@dataclass
class LevelModel:
    layer_count: int  # CLayerList.Count = number of map keys starting with "layer_" (CS:529)
    layers: Dict[str, Optional[List[CTile]]]  # layer name -> tiles in JSON order (None = no "tiles")


def _build_stack(stack_data: Any, root: CTile) -> List[CTile]:  # CS:149-212
    if not isinstance(stack_data, list):
        raise PvUnsupportedInput(f"stack data at {root.layer_name}/{root.pos} is not an array")
    # CS:156 stackData[0].AsEncrypt (missing index -> lazy node -> 0)
    total = as_int(stack_data[0]) if len(stack_data) >= 1 else 0
    inner_ids: Optional[List[str]] = None
    if len(stack_data) >= 2:  # CS:160
        inner_str = _as_string(stack_data[1], "stack inner ids")  # CS:162
        if inner_str:  # CS:163
            ids = inner_str.split("_")  # CS:165
            if len(ids) == total:  # CS:166
                inner_ids = ids
    if total < 0:
        raise CsClientCrash(f"negative stack count at {root.layer_name}/{root.pos} (new string[{total}])")
    tiles: List[CTile] = []
    for i in range(total):  # CS:178-189, GetTileIDArr CS:192-212
        tid = inner_ids[i] if inner_ids is not None else "t0"
        tiles.append(CTile(root.layer_name, root.pos, tid, "", inner_index=i))  # xEffect = "" (CS:184)
    return tiles


def build_level_model(map_obj: Dict[str, Any]) -> LevelModel:
    """CLayerList (CS:520-557) + CTileList (CS:385-424) on a parsed map object."""
    if not isinstance(map_obj, dict):
        raise PvUnsupportedInput("map must be a JSON object")
    layer_count = 0
    layers: Dict[str, Optional[List[CTile]]] = {}
    for key, layer in map_obj.items():
        if not key.startswith("layer_"):  # CS:529
            continue
        layer_count += 1
        if not isinstance(layer, dict):
            raise PvUnsupportedInput(f"{key} is not an object")
        tiles_obj = layer.get("tiles")
        if tiles_obj is None:  # CS:548 — xTiles stays null
            layers[key] = None
            continue
        if isinstance(tiles_obj, list) and not tiles_obj:
            # `"tiles": []` occurs in shards (e.g. Lv599/911/1467): JSONArray enumerates nothing -> 0 tiles.
            layers[key] = []
            continue
        if not isinstance(tiles_obj, dict):
            raise PvUnsupportedInput(f"{key}.tiles is not an object")
        tiles: List[CTile] = []
        for pos, ev in tiles_obj.items():  # CS:392 — JSON key order
            if not isinstance(ev, list):
                raise PvUnsupportedInput(f"{key}/{pos} tile is not an array")
            tid = _as_string(ev[0] if len(ev) >= 1 else None, "tile id")  # CS:399
            eff = _as_string(ev[1] if len(ev) >= 2 else None, "tile effect")  # CS:400
            t = CTile(key, pos, tid, eff)
            if len(ev) > 2 and len(tid.split("_")) >= 2:  # CS:407
                t.stack = _build_stack(ev[2], t)  # CS:412
            tiles.append(t)
        layers[key] = tiles
    return LevelModel(layer_count, layers)


def _layer_tiles(model: LevelModel, i: int) -> List[CTile]:
    name = f"layer_{i}"  # CS:882 / 925 GetLayer($"layer_{i}")
    if name not in model.layers:
        raise CsClientCrash(f"{name} missing while CLayerList.Count={model.layer_count} (NRE, CS:884)")
    tiles = model.layers[name]
    if tiles is None:
        raise CsClientCrash(f"{name} has no tiles (xTiles null, NRE, CS:884)")
    return tiles


def get_empty_tile_list(model: LevelModel, get_all_tile: bool = False) -> List[CTile]:  # CS:870-945
    out: List[CTile] = []
    for i in range(model.layer_count):  # CS:880 / 923
        for t in _layer_tiles(model, i):  # CS:884 / 927
            if not get_all_tile:
                n = t.tile_id_num
                if n == 0:  # CS:888
                    out.append(t)
                elif n == -1:  # CS:892
                    if t.stack is None:
                        raise CsClientCrash(f"{t.layer_name}/{t.pos} id={t.tile_id!r} has no stack info (NRE, CS:894)")
                    for inner in t.stack:  # CS:898-902
                        if inner.tile_id_num == 0:
                            out.append(inner)
            else:
                if t.stack is not None:  # CS:932-935
                    out.extend(t.stack)
                else:
                    out.append(t)  # CS:938
    return out


def get_to_add_index_list(model: LevelModel) -> List[int]:  # CS:1123-1156
    counts = [0] * 16  # CS:1125
    for t in get_empty_tile_list(model, True):  # CS:1129
        n = t.tile_id_num
        if n == 0 or n == -1:  # CS:1135
            continue
        if not 1 <= n <= 16:
            raise CsClientCrash(f"tile id num {n} at {t.layer_name}/{t.pos} -> indexCountArr[{n - 1}] (CS:1137)")
        counts[n - 1] += 1  # CS:1137
    out: List[int] = []
    for i in range(16):  # CS:1140-1153
        odd = counts[i] % 3
        if odd != 0:
            out.extend([i + 1] * (3 - odd))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DistributeTiles (CS:1356-1502)
# ─────────────────────────────────────────────────────────────────────────────
_IMBALANCE_FACTOR = f32(3.0)  # CS:1356
_TILES_PER_COLOR = 3  # CS:1359


def _active_color_count(use_tile_count: int) -> int:  # CS:1361-1362
    return 0 if use_tile_count <= 0 else (use_tile_count + _TILES_PER_COLOR - 1) // _TILES_PER_COLOR


def _color_capacity_of(color_idx: int, use_tile_count: int) -> int:  # CS:1364-1365
    return max(0, min(_TILES_PER_COLOR, use_tile_count - color_idx * _TILES_PER_COLOR))


def _cs_int_div(a: int, b: int) -> int:
    """C# integer division truncates toward zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def distribute_tiles(
    set_length: int,
    tile_type_count: int,
    specified_count: int,
    imbalance_slider_value: float,
    rnd: Optional[ZWellRandom] = None,
) -> List[int]:
    """CS:1372-1502. `imbalance_slider_value` must already be a float32 value."""
    specified_index = 16  # CS:1374
    result: List[int] = []
    non_specified_total = max(0, set_length - specified_count)  # CS:1377

    if tile_type_count > 0 and non_specified_total > 0:  # CS:1379
        active = _active_color_count(tile_type_count)  # CS:1381
        color_cap = [_color_capacity_of(c, tile_type_count) for c in range(active)]  # CS:1382-1388
        total_cap = sum(color_cap)
        color_set = [0] * active  # CS:1390

        assigned = 0  # CS:1393-1401
        if total_cap > 0:
            for c in range(active):
                color_set[c] = _cs_int_div(non_specified_total * color_cap[c], total_cap)
                assigned += color_set[c]

        remainder = non_specified_total - assigned  # CS:1404-1408
        for i in range(remainder):
            color_set[i % active] += 1

        if imbalance_slider_value > 0.0 and active > 1:  # CS:1411
            base_count = f32(f32(float(non_specified_total)) / f32(float(active)))  # CS:1413
            for c in range(active):  # CS:1414-1419
                norm = f32(f32(float(2 * c - (active - 1))) / f32(float(active - 1)))  # CS:1416
                prod = f32(base_count * imbalance_slider_value)  # CS:1417, left-to-right float32
                prod = f32(prod * _IMBALANCE_FACTOR)
                prod = f32(prod * norm)
                delta = round_to_int_unity(prod)
                color_set[c] = max(0, color_set[c] + delta)  # CS:1418

            diff = non_specified_total - sum(color_set)  # CS:1422-1424
            guard = 0
            while diff != 0:  # CS:1426 (safeGuard++ < 10000)
                if guard >= 10000:
                    break
                guard += 1
                if diff > 0:  # CS:1428-1435
                    target = 0
                    for c in range(1, active):
                        if color_set[c] < color_set[target]:
                            target = c
                    color_set[target] += 1
                    diff -= 1
                else:  # CS:1436-1447
                    target = -1
                    for c in range(active):
                        if color_set[c] <= 0:
                            continue
                        if target == -1 or color_set[c] > color_set[target]:
                            target = c
                    if target == -1:
                        break
                    color_set[target] -= 1
                    diff += 1

        for c in range(active):  # CS:1452-1492
            cap = color_cap[c]
            sets = color_set[c]
            if cap <= 0 or sets <= 0:
                continue
            quotient = sets // cap
            rem = sets % cap
            per_slot = [quotient] * cap
            if rem > 0:
                if cap == 1:  # CS:1466-1469
                    per_slot[0] += rem
                else:  # CS:1470-1484
                    order = list(range(cap))
                    if rnd is not None:
                        for i in range(cap - 1, 0, -1):
                            j = rnd.rand(0, i)  # RNG use #1
                            order[i], order[j] = order[j], order[i]
                    for k in range(rem):
                        per_slot[order[k]] += 1
            for o in range(cap):  # CS:1487-1491
                tile_id = c * _TILES_PER_COLOR + o + 1
                result.extend([tile_id] * per_slot[o])

    result.extend([specified_index] * max(0, specified_count))  # CS:1496-1499 (negative -> no loop)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# ShuffleEmptyTiles (CS:1167-1292)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SlotRef:
    layer_name: str
    pos: str
    inner_index: Optional[int]  # None = board tile


@dataclass
class ShuffleResult:
    seed_u32: int
    use_tile_count: int  # maxTileIndex actually used
    slots: List[SlotRef]  # GetEmptyTileList(false) order
    assigned: List[str]  # final tile id per slot (same order)
    to_add: List[int]  # padding list (CS:1123-1156) before consumption
    set_list: List[int]  # DistributeTiles output after the cluster shuffle
    rng_calls: int
    model: LevelModel = field(repr=False)


def shuffle_empty_tiles(
    map_obj: Union[Dict[str, Any], str],
    *,
    rand_seed: Any,
    use_tile_count: Any,
    unlock_tile: Any = 0,
    shuffle_tile: Any = 0,
    type_imbalance: Any = 0,
    skin_tile_count: Optional[int] = None,
    strict: bool = True,
) -> ShuffleResult:
    """Run the client's ShuffleEmptyTiles on `map_obj` (not mutated).

    Field values are raw JSON values (string/number/None) and are read with
    `as_int` exactly like `jsonEvent[...].AsEncrypt.AsInt`.
    strict=True additionally raises PvContractError when the final per-type
    counts (key included, CS:1129 view) are not all divisible by 3.
    """
    if isinstance(map_obj, str):
        map_obj = json.loads(map_obj)
    model = build_level_model(copy.deepcopy(map_obj))

    utc = as_int(use_tile_count)  # CS:1169
    seed_u32 = to_u32(as_int(rand_seed))  # CS:1171 (uint)cLevel.xRandSeed.AsInt
    rnd = ZWellRandom(seed_u32)  # raises for 0 (time-based)

    empty = get_empty_tile_list(model, False)  # CS:1188
    to_add = get_to_add_index_list(model)  # CS:1189
    to_add_initial = list(to_add)

    if utc > 0:  # CS:1190-1193
        max_tile_index = utc
    else:
        if skin_tile_count is None:
            raise PvUnsupportedInput("useTileCount <= 0 needs TileSetting.GetTileCount(skin) (CS:865-868)")
        max_tile_index = skin_tile_count - 1

    n = len(empty)  # CS:1194
    if n == 0:  # CS:1202 — no RNG consumption at all
        return ShuffleResult(seed_u32, max_tile_index, [], [], to_add_initial, [], rnd.calls, model)

    lock_buffer = as_int(unlock_tile)  # CS:1204
    imbalance = f32(f32(float(as_int(type_imbalance))) / f32(10.0))  # CS:1208 AsInt / 10f
    set_list = distribute_tiles(_cs_int_div(n, 3), max_tile_index, lock_buffer, imbalance, rnd)  # CS:1208

    for i in range(len(set_list) - 1, 0, -1):  # CS:1211-1217 cluster-removal Fisher-Yates (RNG use #2)
        j = rnd.rand(0, i)
        set_list[i], set_list[j] = set_list[j], set_list[i]

    for v in set_list:  # CS:1220-1223: 1 / (id*3) — only side effect is DivideByZero for id 0
        if v * 3 == 0:
            raise CsClientCrash("DistributeTiles produced id 0 (DivideByZero, CS:1222)")

    set_count = 0  # CS:1225-1255
    for i in range(n):
        if to_add:
            empty[i].tile_id = f"t{to_add.pop(0)}"  # CS:1231-1236
        else:
            cur = set_count // 3  # CS:1239
            set_count += 1
            if cur >= len(set_list):
                raise CsClientCrash(
                    f"randomTileIndexList[{cur}] out of range (len {len(set_list)}), emptyLen={n} (CS:1253)"
                )
            empty[i].tile_id = f"t{set_list[cur]}"  # CS:1253

    shuffle_count = to_i32(n + as_int(shuffle_tile))  # CS:1271
    for _ in range(shuffle_count):  # RNG use #3
        r1 = rnd.rand(0, n - 1)  # CS:1273
        r2 = rnd.rand(0, n - 1)  # CS:1274
        if not (0 <= r1 < n and 0 <= r2 < n):
            raise CsClientCrash("swap index out of range")
        empty[r1].tile_id, empty[r2].tile_id = empty[r2].tile_id, empty[r1].tile_id  # CS:1279-1285

    result = ShuffleResult(
        seed_u32=seed_u32,
        use_tile_count=max_tile_index,
        slots=[SlotRef(t.layer_name, t.pos, t.inner_index) for t in empty],
        assigned=[t.tile_id for t in empty],
        to_add=to_add_initial,
        set_list=list(set_list),
        rng_calls=rnd.calls,
        model=model,
    )
    if strict:
        _check_divisible(model)
    return result


def shuffle_level_row(row: Dict[str, Any], **kw: Any) -> ShuffleResult:
    """Convenience for a GBoost/townpop level row: {"map": {...}|"<json>", "randSeed", ...}."""
    return shuffle_empty_tiles(
        row["map"],
        rand_seed=row.get("randSeed"),
        use_tile_count=row.get("useTileCount"),
        unlock_tile=row.get("unlockTile"),
        shuffle_tile=row.get("shuffleTile"),
        type_imbalance=row.get("typeImbalance"),
        **kw,
    )


def _check_divisible(model: LevelModel) -> None:
    counts: Dict[int, int] = {}
    for t in get_empty_tile_list(model, True):
        n = t.tile_id_num
        if n == -1:
            continue
        counts[n] = counts.get(n, 0) + 1
    bad = {k: v for k, v in counts.items() if v % 3 != 0}
    if bad:
        raise PvContractError(f"per-type count not divisible by 3 after distribution: {bad}")


# ─────────────────────────────────────────────────────────────────────────────
# Resolved explicit map (for bot/solver evaluation — resolve-then-evaluate)
# ─────────────────────────────────────────────────────────────────────────────
def resolve_map(map_obj: Union[Dict[str, Any], str], result: ShuffleResult) -> Dict[str, Any]:
    """Return a deep copy of `map_obj` with every distributed slot written explicitly.

    Board slot  -> tile[0] = assigned id.
    Stack/craft -> tile[2] = [count, "id0_id1_..."] in client index order (0 = bottom, CS:158),
                   written only for containers that received at least one slot.
    Key/t16 ids are written as "t16" exactly like the client (CS:1235/1253).
    """
    if isinstance(map_obj, str):
        map_obj = json.loads(map_obj)
    out = copy.deepcopy(map_obj)
    touched_stacks: Dict[Tuple[str, str], bool] = {}
    for slot, tid in zip(result.slots, result.assigned):
        tile = out[slot.layer_name]["tiles"][slot.pos]
        if slot.inner_index is None:
            tile[0] = tid
        else:
            touched_stacks[(slot.layer_name, slot.pos)] = True
    for (layer_name, pos) in touched_stacks:
        model_tile = next(t for t in result.model.layers[layer_name] or [] if t.pos == pos)
        ids = [inner.tile_id for inner in (model_tile.stack or [])]
        tile = out[layer_name]["tiles"][pos]
        stack_data = list(tile[2])
        joined = "_".join(ids)
        if len(stack_data) >= 2:
            stack_data[1] = joined
        else:
            stack_data.append(joined)
        tile[2] = stack_data
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Optional: ApplyVisualTileRemap (CS:1307-1354) — NOT part of the default path
# ─────────────────────────────────────────────────────────────────────────────
def apply_visual_tile_remap(assigned: Sequence[str], visual_tile_seed: int) -> List[str]:
    """Pure function over the assigned ids of the empty-tile slots.

    Caller decides applicability (xHasVisualTileSeed and no icon_order, CS:1309-1312).
    """
    pool_size = 15  # CS:1315
    nums = [CTile("", "", tid, "").tile_id_num for tid in assigned]
    present = [False] * (pool_size + 1)
    for v in nums:  # CS:1319-1324
        if 1 <= v <= pool_size:
            present[v] = True
    used = [v for v in range(1, pool_size + 1) if present[v]]  # CS:1325-1326
    if not assigned or not used:  # CS:1313, 1327
        return list(assigned)
    seed_raw = to_i32(visual_tile_seed)
    if seed_raw < 0:  # CS:1330 -> time-based
        raise PvContractError("negative visualTileSeed is time-based (CS:1330)")
    vrnd = ZWellRandom(to_u32(seed_raw + 1))  # CS:1330-1331
    pool = list(range(1, pool_size + 1))  # CS:1334-1335
    for i in range(len(used)):  # CS:1337-1341
        j = vrnd.rand(i, pool_size - 1)
        pool[i], pool[j] = pool[j], pool[i]
    mapping = [0] * (pool_size + 1)
    for k, v in enumerate(used):  # CS:1344-1345
        mapping[v] = pool[k]
    return [f"t{mapping[v]}" if 1 <= v <= pool_size else tid for v, tid in zip(nums, assigned)]  # CS:1348-1353
