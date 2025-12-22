#!/bin/bash

echo "Testing 10 random level generations..."
echo "=================================================="

all_pass=true

for i in {1..10}; do
  DIFF=$(awk "BEGIN {printf \"%.2f\", 0.1 + $i * 0.08}")
  GRID=$((5 + i % 3))
  LAYERS=$((4 + i % 4))

  RESULT=$(curl -s -X POST http://localhost:8000/api/generate \
    -H "Content-Type: application/json" \
    -d "{\"target_difficulty\":$DIFF,\"grid_size\":[$GRID,$GRID],\"max_layers\":$LAYERS,\"tile_types\":[\"t0\",\"t2\",\"t4\",\"t5\"],\"obstacle_types\":[]}")

  TOTAL=$(echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
level = data['level_json']
total = sum(len(level.get(f'layer_{i}', {}).get('tiles', {})) for i in range(level.get('layer', 8)))
print(total)
")

  GRADE=$(echo "$RESULT" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['grade'])")

  REMAINDER=$((TOTAL % 3))

  if [ $REMAINDER -eq 0 ]; then
    echo "Test $i: Total=$TOTAL tiles, Div by 3: true ✅, Grade: $GRADE"
  else
    echo "Test $i: Total=$TOTAL tiles, Div by 3: false ❌, Remainder: $REMAINDER, Grade: $GRADE"
    all_pass=false
  fi
done

echo "=================================================="
if [ "$all_pass" = true ]; then
  echo "Result: ALL PASS ✅"
else
  echo "Result: FAILED ❌"
fi
