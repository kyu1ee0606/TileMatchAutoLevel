"""PV (personalized variants) — seed-driven t0 level variants.

Modules:
- cs_shuffle: bit-exact Python reference port of the game client's
  `DB_Level.ShuffleEmptyTiles` (+ zWellRandom). See
  claudedocs/difficulty_personalization/04_seed_variant_plan.md §A3.
- canonical: canonical map / structHash / typesHash (separate owner).
"""
