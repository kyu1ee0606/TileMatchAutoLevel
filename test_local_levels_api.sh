#!/bin/bash
# Test script for local levels API endpoints

echo "========================================="
echo "Testing Local Levels API"
echo "========================================="
echo ""

# Test 1: List local levels (initially empty)
echo "Test 1: GET /api/simulate/local/list"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/list | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Local levels count: {data['count']}\"); print(f\"Storage path: {data['storage_path']}\")"
echo ""
echo ""

# Test 2: Save a custom level
echo "Test 2: POST /api/simulate/local/save"
echo "-----------------------------------------"
curl -s -X POST http://localhost:8000/api/simulate/local/save \
  -H "Content-Type: application/json" \
  -d '{
    "level_id": "test_level_01",
    "level_data": {
      "layer": 1,
      "randSeed": 0,
      "useTileCount": 3,
      "goals": {"t1": 3, "t2": 3, "t3": 3},
      "max_moves": 50,
      "layer_0": {
        "tiles": {
          "1_1": ["t1"], "1_2": ["t1"], "1_3": ["t1"],
          "2_1": ["t2"], "2_2": ["t2"], "2_3": ["t2"],
          "3_1": ["t3"], "3_2": ["t3"], "3_3": ["t3"]
        },
        "col": 5
      }
    },
    "metadata": {
      "name": "Test Level",
      "description": "API test level",
      "tags": ["test"],
      "difficulty": "easy"
    }
  }' | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Success: {data['success']}\"); print(f\"Level ID: {data['level_id']}\"); print(f\"Message: {data['message']}\")"
echo ""
echo ""

# Test 3: List levels again (should have 1)
echo "Test 3: GET /api/simulate/local/list (after save)"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/list | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Local levels count: {data['count']}\"); [print(f\"  - {level['id']}: {level['name']}\") for level in data['levels']]"
echo ""
echo ""

# Test 4: Get specific level
echo "Test 4: GET /api/simulate/local/test_level_01"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/test_level_01 | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Level ID: {data['level_id']}\"); print(f\"Name: {data['metadata']['name']}\"); print(f\"Tile count: {sum(len(layer.get('tiles', {})) for k, layer in data['level_data'].items() if k.startswith('layer_'))}\"); print(f\"Max moves: {data['level_data']['max_moves']}\")"
echo ""
echo ""

# Test 5: Play the level with bot
echo "Test 5: Simulate test_level_01 with optimal bot"
echo "-----------------------------------------"
LEVEL_DATA=$(curl -s http://localhost:8000/api/simulate/local/test_level_01 | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin)['level_data']))")
curl -s -X POST http://localhost:8000/api/simulate/visual \
  -H "Content-Type: application/json" \
  -d "{
    \"level_json\": $LEVEL_DATA,
    \"bot_types\": [\"optimal\"],
    \"max_moves\": 50,
    \"seed\": 42
  }" | python3 -c "import json, sys; data = json.load(sys.stdin); bot = data['bot_results'][0]; print(f\"Bot: {bot['profile_display']}\"); print(f\"Cleared: {bot['cleared']}\"); print(f\"Total Moves: {bot['total_moves']}\"); print(f\"Final Score: {bot['final_score']}\")"
echo ""
echo ""

# Test 6: Delete level
echo "Test 6: DELETE /api/simulate/local/test_level_01"
echo "-----------------------------------------"
curl -s -X DELETE http://localhost:8000/api/simulate/local/test_level_01 | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Success: {data['success']}\"); print(f\"Message: {data['message']}\")"
echo ""
echo ""

# Test 7: Verify deletion
echo "Test 7: GET /api/simulate/local/list (after delete)"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/list | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Local levels count: {data['count']}\")"
echo ""
echo ""

echo "========================================="
echo "All local levels API tests completed!"
echo "========================================="
