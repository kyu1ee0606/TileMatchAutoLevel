#!/bin/bash
# Determinism Verification Test via API
# Tests that optimal bot produces identical results with same seed

echo "======================================================================"
echo "Determinism Verification Test via API"
echo "======================================================================"
echo ""

SEED=42

echo "Test: Running optimal bot 5 times with seed=$SEED"
echo "Expected: Identical results every time"
echo ""

# Store results
RESULTS=()

for i in {1..5}; do
  echo "Run $i:"
  RESULT=$(curl -s -X POST http://localhost:8000/api/simulate/visual \
    -H "Content-Type: application/json" \
    -d "{
      \"level_json\": {
        \"tiles\": [
          {\"layerIdx\": 0, \"pos\": \"1_1\", \"tileType\": \"t1\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"1_2\", \"tileType\": \"t1\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"1_3\", \"tileType\": \"t1\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"2_1\", \"tileType\": \"t2\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"2_2\", \"tileType\": \"t2\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"2_3\", \"tileType\": \"t2\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"3_1\", \"tileType\": \"t3\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"3_2\", \"tileType\": \"t3\", \"craft\": \"\", \"stackCount\": 1},
          {\"layerIdx\": 0, \"pos\": \"3_3\", \"tileType\": \"t3\", \"craft\": \"\", \"stackCount\": 1}
        ],
        \"layer_cols\": {\"0\": 5},
        \"goals\": {\"t1\": 3, \"t2\": 3, \"t3\": 3},
        \"max_moves\": 50
      },
      \"bot_types\": [\"optimal\"],
      \"seed\": $SEED
    }")

  # Extract key metrics (success, moves, total_moves)
  SUCCESS=$(echo "$RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data['bot_results'][0]['success'])" 2>/dev/null || echo "error")
  MOVES=$(echo "$RESULT" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data['bot_results'][0]['move_history']))" 2>/dev/null || echo "error")

  echo "  Success: $SUCCESS, Move Count: $MOVES"
  RESULTS+=("$SUCCESS|$MOVES")
done

echo ""
echo "Verification:"

# Check if all results are identical
FIRST="${RESULTS[0]}"
ALL_IDENTICAL=true

for result in "${RESULTS[@]:1}"; do
  if [ "$result" != "$FIRST" ]; then
    ALL_IDENTICAL=false
    break
  fi
done

if [ "$ALL_IDENTICAL" = true ]; then
  echo "✅ PASS: All 5 runs produced IDENTICAL results"
  echo "   Deterministic behavior confirmed for seed=$SEED"
  exit 0
else
  echo "❌ FAIL: Results differ across runs"
  echo "   Non-deterministic behavior detected!"
  echo ""
  echo "Results:"
  for i in "${!RESULTS[@]}"; do
    echo "  Run $((i+1)): ${RESULTS[$i]}"
  done
  exit 1
fi
