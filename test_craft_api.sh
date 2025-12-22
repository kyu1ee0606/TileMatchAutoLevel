#!/bin/bash
# Test craft tile emission with optimal bot via API

echo "======================================================================"
echo "Testing Craft Tile Emission Logic via API"
echo "======================================================================"
echo ""

# Test 1: Simple craft tiles
echo "Test 1: Simple craft tiles (spawn not blocked)"
curl -s -X POST http://localhost:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "levelData": {
      "tiles": [
        {"layerIdx": 0, "pos": "3_3", "tileType": "craft_s", "craft": "e", "stackCount": 3},
        {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "1_3", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1}
      ],
      "layer_cols": {"0": 7},
      "goals": {"craft_s": 3},
      "max_moves": 100
    },
    "botProfile": "optimal",
    "simulations": 1
  }' | python3 -m json.tool

echo ""
echo "======================================================================"
echo ""

# Test 2: Craft tiles with blocked spawn position
echo "Test 2: Craft tiles with initially blocked spawn position"
curl -s -X POST http://localhost:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "levelData": {
      "tiles": [
        {"layerIdx": 0, "pos": "3_3", "tileType": "craft_s", "craft": "e", "stackCount": 3},
        {"layerIdx": 0, "pos": "4_3", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "1_1", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "1_2", "tileType": "t1", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_1", "tileType": "t2", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_2", "tileType": "t2", "craft": "", "stackCount": 1},
        {"layerIdx": 0, "pos": "2_3", "tileType": "t2", "craft": "", "stackCount": 1}
      ],
      "layer_cols": {"0": 7},
      "goals": {"craft_s": 3},
      "max_moves": 100
    },
    "botProfile": "optimal",
    "simulations": 1
  }' | python3 -m json.tool

echo ""
echo "======================================================================"
