"""Strong parity for diagnostic traces: traced and untraced runs must choose the same tile sequence.

recorder(cls) adds only a chosen-full_key log (no scoring/RNG side effects). compare() checks the full choice
sequence, outcome, fail reason and final dock; a trace is valid only when parity is exactly True.
"""
_CACHE = {}


def recorder(cls):
    if cls in _CACHE:
        return _CACHE[cls]

    class Rec(cls):
        def __init__(self, *a, **k):
            super().__init__(*a, **k); self.choice_keys = []

        def _select_move_with_profile(self, moves, state, profile):
            sel = super()._select_move_with_profile(moves, state, profile)
            self.choice_keys.append(None if sel is None or sel.tile_state is None else sel.tile_state.full_key)
            return sel
    Rec.__name__ = f'Rec{cls.__name__}'
    _CACHE[cls] = Rec
    return Rec


def compare(traced_bot, traced_end, plain_bot, plain_end, fail_reason):
    same_keys = traced_bot.choice_keys == plain_bot.choice_keys
    same_out = (traced_end.cleared, traced_end.moves_used) == (plain_end.cleared, plain_end.moves_used)
    same_reason = (None if traced_end.cleared else fail_reason(traced_bot, traced_end)) == \
                  (None if plain_end.cleared else fail_reason(plain_bot, plain_end))
    same_dock = [t.full_key for t in traced_end.dock_tiles] == [t.full_key for t in plain_end.dock_tiles]
    return bool(same_keys and same_out and same_reason and same_dock), dict(keys=same_keys, outcome=same_out, reason=same_reason, dock=same_dock)
