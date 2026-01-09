#!/usr/bin/env python3
"""
Generate a full 55-level set with gimmick unlock system.
All 11 gimmicks unlock progressively every 5 levels.
"""
import asyncio
import httpx
import json
import os
from datetime import datetime
from typing import Dict, List, Set

# Gimmick unlock schedule (5-level intervals)
GIMMICK_UNLOCK_LEVELS = {
    "chain": 5,
    "frog": 10,
    "ice": 15,
    "link": 20,
    "grass": 25,
    "bomb": 30,
    "curtain": 35,
    "teleport": 40,
    "crate": 45,
    "craft": 50,
    "stack": 55,
}

ALL_GIMMICKS = list(GIMMICK_UNLOCK_LEVELS.keys())
API_BASE = "http://localhost:8000"
TOTAL_LEVELS = 55
SET_NAME = "GimmickUnlock_55Levels"


def get_unlocked_gimmicks(level_number: int) -> List[str]:
    """Get list of gimmicks unlocked at a given level."""
    return [
        gimmick for gimmick, unlock_level in GIMMICK_UNLOCK_LEVELS.items()
        if unlock_level <= level_number
    ]


def calculate_difficulty(level_number: int, total_levels: int = 55) -> float:
    """
    Calculate target difficulty based on level number.
    Difficulty ranges from 0.15 (level 1) to 0.75 (level 55).
    """
    min_diff = 0.15
    max_diff = 0.75
    progress = (level_number - 1) / (total_levels - 1)
    return min_diff + (max_diff - min_diff) * progress


async def generate_level(client: httpx.AsyncClient, level_number: int) -> Dict:
    """Generate a single level with gimmick unlock system."""
    unlocked = get_unlocked_gimmicks(level_number)
    difficulty = calculate_difficulty(level_number)

    request = {
        "target_difficulty": difficulty,
        "grid_size": [7, 7],
        "max_layers": 5 + min(2, level_number // 20),  # 5-7 layers based on progress
        "obstacle_types": unlocked,
        "auto_select_gimmicks": True,
        "available_gimmicks": unlocked,
        "gimmick_unlock_levels": GIMMICK_UNLOCK_LEVELS,
        "level_number": level_number,
        "gimmick_intensity": 1.0,
        "symmetry_mode": "both",
        "pattern_type": "aesthetic",
    }

    response = await client.post(
        f"{API_BASE}/api/generate/validated",
        json=request,
        timeout=120.0
    )

    if response.status_code != 200:
        raise Exception(f"Level {level_number} generation failed: {response.text}")

    return response.json()


async def generate_level_set():
    """Generate and save the complete 55-level set."""
    # Create set directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    set_id = f"set_{timestamp}_gimmick"
    storage_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "app", "storage", "level_sets", set_id
    )
    os.makedirs(storage_path, exist_ok=True)

    print("=" * 60)
    print(f"Generating {TOTAL_LEVELS} levels with Gimmick Unlock System")
    print(f"Storage: {storage_path}")
    print("=" * 60)
    print(f"\nGimmick unlock schedule:")
    for gimmick, level in sorted(GIMMICK_UNLOCK_LEVELS.items(), key=lambda x: x[1]):
        print(f"  Level {level:2d}: {gimmick}")
    print()

    levels_data = []
    difficulties = []
    actual_difficulties = []
    grades = []

    async with httpx.AsyncClient() as client:
        for level_num in range(1, TOTAL_LEVELS + 1):
            difficulty = calculate_difficulty(level_num)
            unlocked = get_unlocked_gimmicks(level_num)

            print(f"Level {level_num:2d}/{TOTAL_LEVELS} (diff={difficulty:.2f}, "
                  f"gimmicks={len(unlocked)})... ", end="", flush=True)

            try:
                response = await generate_level(client, level_num)
                level_json = response.get("level_json", {})
                actual_diff = response.get("actual_difficulty", 0)
                grade = response.get("grade", "C")

                # Add level metadata
                level_json["level_index"] = level_num
                level_json["name"] = f"{SET_NAME} - Level {level_num}"
                level_json["id"] = f"{set_id}_level_{level_num:03d}"

                # Save level file
                level_filename = f"level_{level_num:03d}.json"
                level_path = os.path.join(storage_path, level_filename)
                with open(level_path, "w", encoding="utf-8") as f:
                    json.dump(level_json, f, indent=2, ensure_ascii=False)

                levels_data.append(level_json)
                difficulties.append(difficulty)
                actual_difficulties.append(actual_diff)
                grades.append(grade)

                print(f"OK (actual={actual_diff:.2f}, grade={grade})")

            except Exception as e:
                print(f"FAILED: {e}")
                # Create placeholder for failed level
                levels_data.append({})
                difficulties.append(difficulty)
                actual_difficulties.append(0)
                grades.append("F")

    # Create metadata
    metadata = {
        "id": set_id,
        "name": SET_NAME,
        "created_at": datetime.now().isoformat(),
        "level_count": TOTAL_LEVELS,
        "difficulty_profile": difficulties,
        "actual_difficulties": actual_difficulties,
        "grades": grades,
        "gimmick_unlock_levels": GIMMICK_UNLOCK_LEVELS,
        "generation_config": {
            "grid_size": [7, 7],
            "max_layers": 7,
            "tile_types": ["t0", "t2", "t4", "t5", "t6"],
            "obstacle_types": ALL_GIMMICKS,
            "goals": [{"type": "craft", "direction": "s", "count": 3}],
            "symmetry_mode": "both",
            "pattern_type": "aesthetic"
        }
    }

    metadata_path = os.path.join(storage_path, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"Set ID: {set_id}")
    print(f"Location: {storage_path}")
    print(f"Total levels: {TOTAL_LEVELS}")
    print(f"Successful: {sum(1 for g in grades if g != 'F')}")
    print(f"Failed: {sum(1 for g in grades if g == 'F')}")
    print(f"\nGrade distribution:")
    for g in ["S", "A", "B", "C", "D", "F"]:
        count = grades.count(g)
        if count > 0:
            print(f"  {g}: {count}")
    print("=" * 60)

    return set_id


if __name__ == "__main__":
    asyncio.run(generate_level_set())
