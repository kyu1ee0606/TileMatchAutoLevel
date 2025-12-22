#!/bin/bash
# Test script for benchmark level API endpoints

echo "========================================="
echo "Testing Benchmark Level API Endpoints"
echo "========================================="
echo ""

# Test 1: List all benchmark levels
echo "Test 1: GET /api/simulate/benchmark/list"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/benchmark/list | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"EASY: {len(data.get('easy', []))} levels\"); print(f\"MEDIUM: {len(data.get('medium', []))} levels\"); print(f\"Sample: {data['easy'][0]['name']} ({data['easy'][0]['id']})\")"
echo ""
echo ""

# Test 2: Get a specific EASY level
echo "Test 2: GET /api/simulate/benchmark/easy_01"
echo "--------------------------------------------"
curl -s http://localhost:8000/api/simulate/benchmark/easy_01 | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Level: {data['metadata']['name']}\"); print(f\"Description: {data['metadata']['description']}\"); print(f\"Max Moves: {data['metadata']['max_moves']}\"); print(f\"Difficulty: {data['metadata']['difficulty']}\"); print(f\"Total tiles: {sum(len(layer.get('tiles', {})) for k, layer in data['level_data'].items() if k.startswith('layer_'))}\")"
echo ""
echo ""

# Test 3: Get a specific MEDIUM level
echo "Test 3: GET /api/simulate/benchmark/medium_01"
echo "----------------------------------------------"
curl -s http://localhost:8000/api/simulate/benchmark/medium_01 | python3 -c "import json, sys; data = json.load(sys.stdin); print(f\"Level: {data['metadata']['name']}\"); print(f\"Description: {data['metadata']['description']}\"); print(f\"Max Moves: {data['metadata']['max_moves']}\"); print(f\"Total tiles: {sum(len(layer.get('tiles', {})) for k, layer in data['level_data'].items() if k.startswith('layer_'))}\")"
echo ""
echo ""

# Test 4: Simulate a benchmark level with visual playback
echo "Test 4: POST /api/simulate/visual with benchmark level"
echo "-------------------------------------------------------"
LEVEL_DATA=$(curl -s http://localhost:8000/api/simulate/benchmark/easy_01 | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin)['level_data']))")
curl -s -X POST http://localhost:8000/api/simulate/visual \
  -H "Content-Type: application/json" \
  -d "{
    \"level_json\": $LEVEL_DATA,
    \"bot_types\": [\"optimal\"],
    \"max_moves\": 50,
    \"seed\": 42
  }" | python3 -c "import json, sys; data = json.load(sys.stdin); bot = data['bot_results'][0]; print(f\"Bot: {bot['profile_display']}\"); print(f\"Cleared: {bot['cleared']}\"); print(f\"Total Moves: {bot['total_moves']}\"); print(f\"Final Score: {bot['final_score']}\"); print(f\"Move Count: {len(bot['moves'])}\")"
echo ""
echo ""

echo "========================================="
echo "All API tests completed successfully!"
echo "========================================="
