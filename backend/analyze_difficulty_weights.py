#!/usr/bin/env python3
"""
Automatic Difficulty Weight Extraction

This script generates levels with various configurations, runs simulations,
and extracts difficulty weights for:
1. Each gimmick/obstacle type
2. Layer depth (how covered tiles are)
3. Tile count impact

Output: Derived weights/coefficients for difficulty calculation
"""
import sys
sys.path.insert(0, '.')

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple, Optional
import statistics

from app.core.generator import LevelGenerator, GenerationParams
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import get_profile, BotType, PREDEFINED_PROFILES

# Available obstacle types
OBSTACLE_TYPES = [
    "chain",
    "frog",
    "link",  # Will generate link_n, link_s, link_e, link_w
    "ice",
    "grass",
    "bomb",
    "curtain",
]

@dataclass
class BotResult:
    """Result from a single bot profile"""
    bot_type: str
    clear_rate: float
    avg_moves: float
    min_moves: int
    max_moves_used: int

@dataclass
class LevelAnalysisResult:
    """Result of analyzing a single level"""
    level_id: str
    config: Dict[str, Any]

    # Level metrics
    total_tiles: int
    active_layers: int
    obstacle_counts: Dict[str, int]
    layer_blocking_score: float

    # Simulation results (from multiple bots)
    bot_results: Dict[str, BotResult] = field(default_factory=dict)
    avg_clear_rate: float = 0.0  # Average across bots
    avg_moves: float = 0.0
    min_moves: int = 0
    max_moves_used: int = 0
    move_efficiency: float = 0.0  # moves / tiles

    # Derived difficulty
    difficulty_score: float = 0.0  # 0-1 based on simulation

    @property
    def clear_rate(self) -> float:
        """Average clear rate across all bots"""
        if not self.bot_results:
            return 0.0
        return statistics.mean([r.clear_rate for r in self.bot_results.values()])

@dataclass
class AnalysisData:
    """Aggregated analysis data"""
    results: List[LevelAnalysisResult] = field(default_factory=list)

    # Grouped by obstacle type
    by_obstacle: Dict[str, List[LevelAnalysisResult]] = field(default_factory=lambda: defaultdict(list))

    # Grouped by layer count
    by_layers: Dict[int, List[LevelAnalysisResult]] = field(default_factory=lambda: defaultdict(list))

    # Grouped by tile count range
    by_tile_range: Dict[str, List[LevelAnalysisResult]] = field(default_factory=lambda: defaultdict(list))


def count_obstacles_in_level(level_json: Dict[str, Any]) -> Dict[str, int]:
    """Count each obstacle type in a level"""
    counts = defaultdict(int)
    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        tiles = level_json.get(layer_key, {}).get("tiles", {})

        for pos, tile_data in tiles.items():
            if isinstance(tile_data, list) and len(tile_data) >= 2:
                attr = tile_data[1] if tile_data[1] else ""

                if attr == "chain":
                    counts["chain"] += 1
                elif attr == "frog":
                    counts["frog"] += 1
                elif attr.startswith("link_"):
                    counts["link"] += 1
                elif attr.startswith("ice"):
                    counts["ice"] += 1
                elif attr.startswith("grass"):
                    counts["grass"] += 1
                elif attr.startswith("bomb") or attr.isdigit():
                    counts["bomb"] += 1
                elif attr.startswith("curtain"):
                    counts["curtain"] += 1

    return dict(counts)


def calculate_layer_blocking(level_json: Dict[str, Any]) -> float:
    """Calculate layer blocking score"""
    num_layers = level_json.get("layer", 8)
    layer_positions: Dict[int, set] = {}

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        tiles = level_json.get(layer_key, {}).get("tiles", {})
        if tiles:
            layer_positions[i] = set(tiles.keys())

    blocking_score = 0.0
    for upper_layer in range(num_layers - 1, 0, -1):
        upper_positions = layer_positions.get(upper_layer, set())
        for lower_layer in range(upper_layer - 1, -1, -1):
            lower_positions = layer_positions.get(lower_layer, set())
            overlap = len(upper_positions & lower_positions)
            layer_weight = (num_layers - upper_layer) * 0.5
            blocking_score += overlap * layer_weight

    return blocking_score


def count_total_tiles(level_json: Dict[str, Any]) -> Tuple[int, int]:
    """Count total tiles and active layers"""
    total = 0
    active_layers = 0
    num_layers = level_json.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        tiles = level_json.get(layer_key, {}).get("tiles", {})
        if tiles:
            active_layers += 1
            total += len(tiles)

    return total, active_layers


# Bot profiles to test (ordered from weakest to strongest)
TEST_BOT_TYPES = [
    BotType.NOVICE,   # Weakest - random-ish
    BotType.CASUAL,   # Weak - basic strategy
    BotType.AVERAGE,  # Medium - greedy
    BotType.EXPERT,   # Strong - smart lookahead
]


def generate_and_analyze(
    generator: LevelGenerator,
    simulator: BotSimulator,
    params: GenerationParams,
    level_id: str,
    iterations: int = 10
) -> Optional[LevelAnalysisResult]:
    """Generate a level and analyze it through simulation with multiple bots"""
    try:
        result = generator.generate(params)
        level_json = result.level_json

        # Extract metrics
        total_tiles, active_layers = count_total_tiles(level_json)
        obstacle_counts = count_obstacles_in_level(level_json)
        blocking_score = calculate_layer_blocking(level_json)

        # Run simulation with multiple bot profiles
        bot_results = {}
        all_clear_rates = []
        all_moves = []

        for bot_type in TEST_BOT_TYPES:
            profile = get_profile(bot_type)
            sim_result = simulator.simulate_with_profile(
                level_json, profile, iterations=iterations
            )

            bot_results[bot_type.value] = BotResult(
                bot_type=bot_type.value,
                clear_rate=sim_result.clear_rate,
                avg_moves=sim_result.avg_moves,
                min_moves=sim_result.min_moves,
                max_moves_used=sim_result.max_moves,
            )

            all_clear_rates.append(sim_result.clear_rate)
            all_moves.append(sim_result.avg_moves)

        # Calculate combined metrics
        avg_clear_rate = statistics.mean(all_clear_rates)
        avg_moves = statistics.mean(all_moves)

        if total_tiles > 0 and avg_moves > 0:
            move_efficiency = avg_moves / total_tiles
        else:
            move_efficiency = 1.0

        # Calculate difficulty score
        # Weight NOVICE and CASUAL more heavily as they show more variation
        novice_rate = bot_results.get("novice", BotResult("", 1.0, 0, 0, 0)).clear_rate
        casual_rate = bot_results.get("casual", BotResult("", 1.0, 0, 0, 0)).clear_rate
        average_rate = bot_results.get("average", BotResult("", 1.0, 0, 0, 0)).clear_rate

        # Weighted clear difficulty (lower clear rate = harder)
        weighted_clear = (
            (1.0 - novice_rate) * 0.4 +
            (1.0 - casual_rate) * 0.35 +
            (1.0 - average_rate) * 0.25
        )

        # Combined difficulty score
        difficulty_score = weighted_clear * 0.7 + min(1.0, move_efficiency) * 0.3

        return LevelAnalysisResult(
            level_id=level_id,
            config={
                "grid_size": params.grid_size,
                "max_layers": params.max_layers,
                "obstacle_types": params.obstacle_types,
            },
            total_tiles=total_tiles,
            active_layers=active_layers,
            obstacle_counts=obstacle_counts,
            layer_blocking_score=blocking_score,
            bot_results=bot_results,
            avg_clear_rate=avg_clear_rate,
            avg_moves=avg_moves,
            min_moves=min([r.min_moves for r in bot_results.values()]),
            max_moves_used=max([r.max_moves_used for r in bot_results.values()]),
            move_efficiency=move_efficiency,
            difficulty_score=difficulty_score,
        )

    except Exception as e:
        print(f"  Error generating/analyzing {level_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_baseline_tests(generator, simulator, data: AnalysisData, num_per_config: int = 5):
    """Run baseline tests with no obstacles"""
    print("\n[1] Baseline Tests (No Obstacles)")
    print("-" * 40)

    layer_configs = [3, 5, 7]

    for layers in layer_configs:
        print(f"\n  Layers: {layers}")
        for i in range(num_per_config):
            params = GenerationParams(
                grid_size=[7, 7],
                max_layers=layers,
                tile_types=["t0", "t1", "t2", "t3", "t4"],
                obstacle_types=[],  # No obstacles
                goals=[],
                symmetry_mode="none",
                pattern_type="geometric",
                target_difficulty=0.3
            )

            result = generate_and_analyze(
                generator, simulator, params,
                f"baseline_L{layers}_{i+1}"
            )

            if result:
                data.results.append(result)
                data.by_layers[layers].append(result)
                data.by_obstacle["none"].append(result)

                # Show per-bot results
                novice_rate = result.bot_results.get("novice", BotResult("", 0, 0, 0, 0)).clear_rate
                casual_rate = result.bot_results.get("casual", BotResult("", 0, 0, 0, 0)).clear_rate
                print(f"    Test {i+1}: tiles={result.total_tiles}, "
                      f"novice={novice_rate:.0%}, casual={casual_rate:.0%}, "
                      f"diff={result.difficulty_score:.3f}")


def run_single_obstacle_tests(generator, simulator, data: AnalysisData, num_per_config: int = 5):
    """Test each obstacle type individually"""
    print("\n[2] Single Obstacle Type Tests")
    print("-" * 40)

    for obstacle in OBSTACLE_TYPES:
        print(f"\n  Obstacle: {obstacle}")

        for i in range(num_per_config):
            params = GenerationParams(
                grid_size=[7, 7],
                max_layers=5,
                tile_types=["t0", "t1", "t2", "t3", "t4"],
                obstacle_types=[obstacle],
                goals=[],
                symmetry_mode="none",
                pattern_type="geometric",
                target_difficulty=0.4
            )

            result = generate_and_analyze(
                generator, simulator, params,
                f"single_{obstacle}_{i+1}"
            )

            if result:
                data.results.append(result)
                data.by_obstacle[obstacle].append(result)
                obs_count = result.obstacle_counts.get(obstacle, 0)
                novice_rate = result.bot_results.get("novice", BotResult("", 0, 0, 0, 0)).clear_rate
                print(f"    Test {i+1}: {obstacle}={obs_count}, "
                      f"novice={novice_rate:.0%}, diff={result.difficulty_score:.3f}")


def run_layer_depth_tests(generator, simulator, data: AnalysisData, num_per_config: int = 5):
    """Test different layer depths"""
    print("\n[3] Layer Depth Tests")
    print("-" * 40)

    layer_configs = [2, 3, 4, 5, 6, 7, 8]

    for layers in layer_configs:
        print(f"\n  Layers: {layers}")

        for i in range(num_per_config):
            params = GenerationParams(
                grid_size=[7, 7],
                max_layers=layers,
                tile_types=["t0", "t1", "t2", "t3", "t4"],
                obstacle_types=["chain"],  # Consistent obstacle
                goals=[],
                symmetry_mode="none",
                pattern_type="geometric",
                target_difficulty=0.4
            )

            result = generate_and_analyze(
                generator, simulator, params,
                f"layers_{layers}_{i+1}"
            )

            if result:
                data.results.append(result)
                data.by_layers[layers].append(result)
                novice_rate = result.bot_results.get("novice", BotResult("", 0, 0, 0, 0)).clear_rate
                print(f"    Test {i+1}: active={result.active_layers}, blocking={result.layer_blocking_score:.1f}, "
                      f"novice={novice_rate:.0%}, diff={result.difficulty_score:.3f}")


def run_combined_obstacle_tests(generator, simulator, data: AnalysisData, num_per_config: int = 3):
    """Test combinations of obstacles"""
    print("\n[4] Combined Obstacle Tests")
    print("-" * 40)

    combos = [
        ["chain", "frog"],
        ["chain", "ice"],
        ["frog", "link"],
        ["chain", "frog", "ice"],
        ["chain", "frog", "link", "ice"],
    ]

    for combo in combos:
        combo_name = "+".join(combo)
        print(f"\n  Combo: {combo_name}")

        for i in range(num_per_config):
            params = GenerationParams(
                grid_size=[7, 7],
                max_layers=5,
                tile_types=["t0", "t1", "t2", "t3", "t4"],
                obstacle_types=combo,
                goals=[],
                symmetry_mode="none",
                pattern_type="geometric",
                target_difficulty=0.5
            )

            result = generate_and_analyze(
                generator, simulator, params,
                f"combo_{combo_name}_{i+1}"
            )

            if result:
                data.results.append(result)
                for obs in combo:
                    if result.obstacle_counts.get(obs, 0) > 0:
                        data.by_obstacle[obs].append(result)
                novice_rate = result.bot_results.get("novice", BotResult("", 0, 0, 0, 0)).clear_rate
                print(f"    Test {i+1}: {result.obstacle_counts}, "
                      f"novice={novice_rate:.0%}, diff={result.difficulty_score:.3f}")


def calculate_weights(data: AnalysisData) -> Dict[str, Any]:
    """Calculate difficulty weights from collected data"""
    print("\n" + "=" * 60)
    print("WEIGHT EXTRACTION RESULTS")
    print("=" * 60)

    weights = {}

    # 1. Baseline difficulty (no obstacles)
    baseline_results = data.by_obstacle.get("none", [])
    if baseline_results:
        baseline_clear = statistics.mean([r.avg_clear_rate for r in baseline_results])
        baseline_moves = statistics.mean([r.avg_moves for r in baseline_results])
        baseline_tiles = statistics.mean([r.total_tiles for r in baseline_results])
        baseline_difficulty = statistics.mean([r.difficulty_score for r in baseline_results])

        # Per-bot baseline
        print(f"\n[Baseline] No obstacles:")
        print(f"  Avg Tiles: {baseline_tiles:.1f}")
        print(f"  Avg Difficulty Score: {baseline_difficulty:.3f}")

        for bot_type in TEST_BOT_TYPES:
            bot_key = bot_type.value
            bot_clears = [r.bot_results.get(bot_key, BotResult("", 0, 0, 0, 0)).clear_rate
                         for r in baseline_results if bot_key in r.bot_results]
            if bot_clears:
                print(f"    {bot_key}: {statistics.mean(bot_clears):.2%} clear rate")
    else:
        baseline_clear = 1.0
        baseline_moves = 50
        baseline_tiles = 60
        baseline_difficulty = 0.3

    # 2. Calculate per-obstacle weight
    print("\n[Per-Obstacle Difficulty Impact]")
    print("-" * 40)

    obstacle_weights = {}
    for obs_type in OBSTACLE_TYPES:
        results = data.by_obstacle.get(obs_type, [])
        if not results:
            continue

        # Filter results that actually have this obstacle
        with_obs = [r for r in results if r.obstacle_counts.get(obs_type, 0) > 0]
        if not with_obs:
            continue

        avg_count = statistics.mean([r.obstacle_counts.get(obs_type, 0) for r in with_obs])
        avg_clear = statistics.mean([r.avg_clear_rate for r in with_obs])
        avg_moves = statistics.mean([r.avg_moves for r in with_obs])
        avg_difficulty = statistics.mean([r.difficulty_score for r in with_obs])

        # Calculate per-bot clear rates
        per_bot_clears = {}
        for bot_type in TEST_BOT_TYPES:
            bot_key = bot_type.value
            bot_clears = [r.bot_results.get(bot_key, BotResult("", 0, 0, 0, 0)).clear_rate
                         for r in with_obs if bot_key in r.bot_results]
            if bot_clears:
                per_bot_clears[bot_key] = statistics.mean(bot_clears)

        # Calculate impact based on difficulty score difference from baseline
        difficulty_impact = (avg_difficulty - baseline_difficulty) / max(avg_count, 1)

        # Calculate impact per obstacle
        clear_impact = (baseline_clear - avg_clear) / max(avg_count, 1)
        move_impact = (avg_moves - baseline_moves) / max(avg_count, 1)

        # Improved weight calculation: use difficulty score directly
        # Scale: 0-10 where 10 is maximum difficulty
        weight = difficulty_impact * 100  # Scale up for visibility
        weight = max(0, min(10, weight))  # Clamp to 0-10

        obstacle_weights[obs_type] = {
            "weight": round(weight, 2),
            "avg_count": round(avg_count, 1),
            "avg_difficulty": round(avg_difficulty, 3),
            "difficulty_impact_per_obs": round(difficulty_impact, 4),
            "per_bot_clears": {k: round(v, 3) for k, v in per_bot_clears.items()},
            "avg_moves": round(avg_moves, 1),
        }

        print(f"\n  {obs_type}:")
        print(f"    Avg Count: {avg_count:.1f}")
        print(f"    Avg Difficulty: {avg_difficulty:.3f} (baseline: {baseline_difficulty:.3f})")
        for bot_key, clear_rate in per_bot_clears.items():
            print(f"      {bot_key}: {clear_rate:.2%}")
        print(f"    Difficulty Impact per obstacle: {difficulty_impact:.4f}")
        print(f"    --> WEIGHT: {weight:.2f}")

    weights["obstacles"] = obstacle_weights

    # 3. Calculate layer depth impact
    print("\n[Layer Depth Impact]")
    print("-" * 40)

    layer_weights = {}
    for layer_count, results in sorted(data.by_layers.items()):
        if not results:
            continue

        avg_clear = statistics.mean([r.clear_rate for r in results])
        avg_moves = statistics.mean([r.avg_moves for r in results])
        avg_blocking = statistics.mean([r.layer_blocking_score for r in results])
        avg_difficulty = statistics.mean([r.difficulty_score for r in results])

        layer_weights[layer_count] = {
            "avg_clear_rate": round(avg_clear, 3),
            "avg_moves": round(avg_moves, 1),
            "avg_blocking_score": round(avg_blocking, 1),
            "avg_difficulty": round(avg_difficulty, 3),
        }

        print(f"\n  {layer_count} layers:")
        print(f"    Avg Clear Rate: {avg_clear:.2%}")
        print(f"    Avg Moves: {avg_moves:.1f}")
        print(f"    Avg Blocking Score: {avg_blocking:.1f}")
        print(f"    Avg Difficulty: {avg_difficulty:.3f}")

    # Calculate layer weight coefficient
    if len(layer_weights) >= 2:
        layers = sorted(layer_weights.keys())
        difficulties = [layer_weights[l]["avg_difficulty"] for l in layers]

        # Simple linear regression to find coefficient
        n = len(layers)
        sum_x = sum(layers)
        sum_y = sum(difficulties)
        sum_xy = sum(x * y for x, y in zip(layers, difficulties))
        sum_x2 = sum(x * x for x in layers)

        if n * sum_x2 - sum_x * sum_x != 0:
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
            layer_coefficient = slope * 100  # Scale for readability
        else:
            layer_coefficient = 0

        print(f"\n  --> LAYER WEIGHT COEFFICIENT: {layer_coefficient:.3f} per layer")
        weights["layer_coefficient"] = round(layer_coefficient, 3)

    weights["layers"] = layer_weights

    # 4. Calculate blocking weight
    print("\n[Layer Blocking Impact]")
    print("-" * 40)

    # Correlate blocking score with difficulty
    all_with_blocking = [r for r in data.results if r.layer_blocking_score > 0]
    if all_with_blocking:
        blocking_scores = [r.layer_blocking_score for r in all_with_blocking]
        difficulties = [r.difficulty_score for r in all_with_blocking]

        # Simple correlation
        n = len(blocking_scores)
        if n > 1:
            mean_b = statistics.mean(blocking_scores)
            mean_d = statistics.mean(difficulties)

            numerator = sum((b - mean_b) * (d - mean_d) for b, d in zip(blocking_scores, difficulties))
            denom_b = sum((b - mean_b) ** 2 for b in blocking_scores) ** 0.5
            denom_d = sum((d - mean_d) ** 2 for d in difficulties) ** 0.5

            if denom_b > 0 and denom_d > 0:
                correlation = numerator / (denom_b * denom_d)
            else:
                correlation = 0

            # Weight based on correlation and scale
            blocking_weight = abs(correlation) * 0.5  # Scale factor

            print(f"  Correlation with difficulty: {correlation:.3f}")
            print(f"  --> BLOCKING WEIGHT: {blocking_weight:.4f}")
            weights["blocking_weight"] = round(blocking_weight, 4)

    # 5. Tile count impact
    print("\n[Tile Count Impact]")
    print("-" * 40)

    tile_ranges = [
        ("30-60", 30, 60),
        ("60-90", 60, 90),
        ("90-120", 90, 120),
        ("120+", 120, 9999),
    ]

    tile_weights = {}
    for range_name, min_tiles, max_tiles in tile_ranges:
        in_range = [r for r in data.results if min_tiles <= r.total_tiles < max_tiles]
        if not in_range:
            continue

        avg_clear = statistics.mean([r.clear_rate for r in in_range])
        avg_moves = statistics.mean([r.avg_moves for r in in_range])
        avg_difficulty = statistics.mean([r.difficulty_score for r in in_range])

        tile_weights[range_name] = {
            "count": len(in_range),
            "avg_clear_rate": round(avg_clear, 3),
            "avg_moves": round(avg_moves, 1),
            "avg_difficulty": round(avg_difficulty, 3),
        }

        print(f"\n  {range_name} tiles ({len(in_range)} levels):")
        print(f"    Avg Clear Rate: {avg_clear:.2%}")
        print(f"    Avg Moves: {avg_moves:.1f}")
        print(f"    Avg Difficulty: {avg_difficulty:.3f}")

    weights["tile_ranges"] = tile_weights

    return weights


def generate_algorithm(weights: Dict[str, Any]) -> str:
    """Generate a difficulty calculation algorithm from weights"""
    algo = """
# ============================================================
# AUTO-EXTRACTED DIFFICULTY CALCULATION ALGORITHM
# ============================================================

def calculate_difficulty(level_json):
    '''
    Calculate difficulty score based on extracted weights.

    Returns: float (0.0 - 1.0, where 1.0 is hardest)
    '''
    score = 0.0

    # 1. Obstacle contributions
    obstacle_weights = {
"""

    for obs, data in weights.get("obstacles", {}).items():
        algo += f"        '{obs}': {data['weight']},  # Impact per obstacle\n"

    algo += """    }

    obstacle_counts = count_obstacles(level_json)
    for obs_type, count in obstacle_counts.items():
        if obs_type in obstacle_weights:
            score += count * obstacle_weights[obs_type]

    # 2. Layer depth contribution
"""

    layer_coef = weights.get("layer_coefficient", 0.05)
    algo += f"    layer_coefficient = {layer_coef}  # Per additional layer\n"

    algo += """    active_layers = count_active_layers(level_json)
    score += active_layers * layer_coefficient

    # 3. Layer blocking contribution
"""

    blocking_weight = weights.get("blocking_weight", 0.01)
    algo += f"    blocking_weight = {blocking_weight}\n"

    algo += """    blocking_score = calculate_layer_blocking(level_json)
    score += blocking_score * blocking_weight

    # 4. Tile count contribution (normalized)
    total_tiles = count_tiles(level_json)
    tile_factor = total_tiles / 100.0  # Normalize to ~1.0 for 100 tiles
    score *= (0.5 + tile_factor * 0.5)  # Scale by tile count

    # Normalize to 0-1 range
    return min(1.0, max(0.0, score / 100.0))
"""

    return algo


def main():
    print("=" * 60)
    print("AUTOMATIC DIFFICULTY WEIGHT EXTRACTION")
    print("=" * 60)
    print("\nThis will generate levels and run simulations to extract")
    print("difficulty weights for obstacles and layer configurations.")
    print(f"Testing with {len(TEST_BOT_TYPES)} bot profiles: {[b.value for b in TEST_BOT_TYPES]}\n")

    start_time = time.time()

    generator = LevelGenerator()
    simulator = BotSimulator()

    data = AnalysisData()

    # Run all test suites
    run_baseline_tests(generator, simulator, data, num_per_config=3)
    run_single_obstacle_tests(generator, simulator, data, num_per_config=3)
    run_layer_depth_tests(generator, simulator, data, num_per_config=3)
    run_combined_obstacle_tests(generator, simulator, data, num_per_config=2)

    # Calculate weights
    weights = calculate_weights(data)

    # Generate algorithm
    algo = generate_algorithm(weights)

    print("\n" + "=" * 60)
    print("GENERATED ALGORITHM")
    print("=" * 60)
    print(algo)

    # Save results
    results_file = "difficulty_weights_extracted.json"
    with open(results_file, 'w') as f:
        json.dump(weights, f, indent=2)
    print(f"\nWeights saved to: {results_file}")

    elapsed = time.time() - start_time
    print(f"\nTotal time: {elapsed:.1f}s")
    print(f"Total levels analyzed: {len(data.results)}")

    return weights


if __name__ == "__main__":
    main()
