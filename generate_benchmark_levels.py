#!/usr/bin/env python3
"""
Automated Benchmark Level Generator

Generates benchmark levels with configurable parameters and automatic validation.

Usage:
    python3 generate_benchmark_levels.py --tier medium --count 10 --validate
    python3 generate_benchmark_levels.py --tier hard --start-id hard_01 --validate
    python3 generate_benchmark_levels.py --config custom_config.json

Examples:
    # Generate 10 MEDIUM tier levels with validation
    python3 generate_benchmark_levels.py --tier medium --count 10 --validate

    # Generate single level with specific parameters
    python3 generate_benchmark_levels.py --tier hard --count 1 --tile-types 8 --layers 3

    # Generate from JSON configuration
    python3 generate_benchmark_levels.py --config level_config.json
"""

import sys
import json
import argparse
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import random

sys.path.insert(0, '/Users/casualdev/TileMatchAutoLevel/backend')

from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from app.models.benchmark_level import DifficultyTier


@dataclass
class LevelGenerationConfig:
    """Configuration for generating a single level."""
    tier: str  # "easy", "medium", "hard", "expert", "impossible"
    level_id: str
    name: str
    description: str
    tags: List[str]

    # Level parameters
    tile_types: int  # Number of different tile types (3-12)
    tile_count: int  # Total number of tiles (must be divisible by 3)
    layers: int  # Number of layers (1-4)
    max_moves: int  # Maximum moves allowed

    # Effect tiles
    ice_tiles: int = 0
    grass_tiles: int = 0
    link_tiles: int = 0

    # Expected clear rates (will be calibrated if not provided)
    expected_clear_rates: Optional[Dict[str, float]] = None

    # Generation parameters
    seed: int = 42
    grid_cols: int = 9
    grid_rows: int = 9


@dataclass
class GeneratedLevel:
    """A generated benchmark level with metadata and validation results."""
    config: LevelGenerationConfig
    level_json: Dict
    actual_clear_rates: Dict[str, float]
    validation_status: str  # "pass", "warn", "fail"
    suggestions: List[str]


class LevelGenerator:
    """Automated level generator with difficulty calibration."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.simulator = BotSimulator()
        random.seed(seed)

    def generate_level(self, config: LevelGenerationConfig) -> Dict:
        """
        Generate a level based on configuration.

        Returns:
            level_json compatible with simulator format
        """
        # Validate tile count
        if config.tile_count % 3 != 0:
            raise ValueError(f"Tile count must be divisible by 3, got {config.tile_count}")

        # Generate tile type identifiers
        tile_type_ids = [f"t{i+1}" for i in range(config.tile_types)]

        # Calculate tiles per type (must be divisible by 3)
        tiles_per_type = config.tile_count // config.tile_types
        if tiles_per_type % 3 != 0:
            # Adjust to nearest multiple of 3
            tiles_per_type = (tiles_per_type // 3) * 3

        # Generate goals
        goals = {tid: tiles_per_type for tid in tile_type_ids}

        # Adjust total if needed
        total_goal_tiles = sum(goals.values())
        if total_goal_tiles != config.tile_count:
            # Distribute remaining tiles
            remaining = config.tile_count - total_goal_tiles
            for i in range(abs(remaining) // 3):
                tile_id = tile_type_ids[i % len(tile_type_ids)]
                goals[tile_id] += 3 if remaining > 0 else -3

        # Generate tile positions across layers
        level_json = {
            "layer": config.layers,
            "randSeed": config.seed,
            "useTileCount": config.tile_types,
            "goals": goals,
            "max_moves": config.max_moves,
        }

        # Generate tiles for each layer
        all_positions = self._generate_positions(config.grid_cols, config.grid_rows, config.tile_count)

        # Create full tile pool based on goals
        tile_pool = []
        for tile_id, count in goals.items():
            tile_pool.extend([tile_id] * count)
        random.shuffle(tile_pool)

        # Distribute tiles across layers
        positions_per_layer = len(all_positions) // config.layers

        for layer_idx in range(config.layers):
            layer_key = f"layer_{layer_idx}"
            start_idx = layer_idx * positions_per_layer
            end_idx = start_idx + positions_per_layer if layer_idx < config.layers - 1 else len(all_positions)
            layer_positions = all_positions[start_idx:end_idx]

            # Calculate tiles for this layer
            tiles_start = layer_idx * (len(tile_pool) // config.layers)
            tiles_end = tiles_start + (len(tile_pool) // config.layers) if layer_idx < config.layers - 1 else len(tile_pool)
            layer_tiles = tile_pool[tiles_start:tiles_end]

            # Assign tiles to positions
            tiles_dict = {}
            for i, pos in enumerate(layer_positions):
                if i < len(layer_tiles):
                    tiles_dict[pos] = [layer_tiles[i]]

            level_json[layer_key] = {
                "tiles": tiles_dict,
                "col": config.grid_cols,
            }

        # Add effect tiles if specified
        if config.ice_tiles > 0 or config.grass_tiles > 0 or config.link_tiles > 0:
            level_json["effects"] = self._add_effect_tiles(
                config, all_positions[:positions_per_layer]
            )

        return level_json

    def _generate_positions(self, cols: int, rows: int, tile_count: int) -> List[str]:
        """Generate tile positions on grid."""
        all_positions = []

        # Generate grid positions
        for row in range(1, rows + 1):
            for col in range(1, cols + 1):
                all_positions.append(f"{row}_{col}")

        # Shuffle and take required number
        random.shuffle(all_positions)
        return all_positions[:tile_count]


    def _add_effect_tiles(
        self, config: LevelGenerationConfig, positions: List[str]
    ) -> Dict[str, List[str]]:
        """Add effect tiles (ICE, GRASS, LINK) to level."""
        effects = {}
        available_positions = positions.copy()
        random.shuffle(available_positions)

        pos_idx = 0

        # Add ICE tiles
        for _ in range(config.ice_tiles):
            if pos_idx < len(available_positions):
                effects[available_positions[pos_idx]] = ["ICE"]
                pos_idx += 1

        # Add GRASS tiles
        for _ in range(config.grass_tiles):
            if pos_idx < len(available_positions):
                effects[available_positions[pos_idx]] = ["GRASS"]
                pos_idx += 1

        # Add LINK tiles (need pairs)
        link_pairs = config.link_tiles // 2
        for _ in range(link_pairs):
            if pos_idx + 1 < len(available_positions):
                link_id = f"link_{_}"
                effects[available_positions[pos_idx]] = [f"LINK:{link_id}"]
                effects[available_positions[pos_idx + 1]] = [f"LINK:{link_id}"]
                pos_idx += 2

        return effects

    def validate_level(
        self, level_json: Dict, config: LevelGenerationConfig, iterations: int = 100
    ) -> Tuple[Dict[str, float], str, List[str]]:
        """
        Validate generated level by testing with all bots.

        Returns:
            (actual_clear_rates, validation_status, suggestions)
        """
        actual_clear_rates = {}
        deviations = []
        suggestions = []

        bot_types = [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]

        # Run simulations
        for bot_type in bot_types:
            profile = get_profile(bot_type)
            result = self.simulator.simulate_with_profile(
                level_json, profile, iterations=iterations, max_moves=config.max_moves, seed=config.seed
            )
            actual_clear_rates[bot_type.value] = result.clear_rate

            # Calculate deviation if expected rates provided
            if config.expected_clear_rates and bot_type.value in config.expected_clear_rates:
                expected = config.expected_clear_rates[bot_type.value]
                deviation = abs(result.clear_rate - expected) * 100
                deviations.append((bot_type.value, deviation, result.clear_rate, expected))

        # Determine validation status
        if not config.expected_clear_rates:
            return actual_clear_rates, "uncalibrated", ["No expected clear rates provided - use actual rates"]

        tolerance = 15.0
        max_deviation = max(d[1] for d in deviations) if deviations else 0

        if max_deviation <= tolerance:
            validation_status = "pass"
        elif max_deviation <= tolerance * 1.5:
            validation_status = "warn"
        else:
            validation_status = "fail"

            # Generate suggestions
            avg_actual = sum(d[2] for d in deviations) / len(deviations)
            avg_expected = sum(d[3] for d in deviations) / len(deviations)

            if avg_actual > avg_expected + 0.1:
                suggestions.append("Level too easy - increase difficulty:")
                suggestions.append(f"  - Increase tile count by {int(config.tile_count * 0.2)} tiles")
                suggestions.append(f"  - Add 1-2 more tile types")
                suggestions.append(f"  - Reduce max_moves to {int(config.max_moves * 0.8)}")
                suggestions.append("  - Add effect tiles (ICE, GRASS, LINK)")
            elif avg_actual < avg_expected - 0.1:
                suggestions.append("Level too hard - decrease difficulty:")
                suggestions.append(f"  - Reduce tile count by {int(config.tile_count * 0.2)} tiles")
                suggestions.append(f"  - Remove 1-2 tile types")
                suggestions.append(f"  - Increase max_moves to {int(config.max_moves * 1.2)}")
                suggestions.append("  - Remove or reduce effect tiles")

        return actual_clear_rates, validation_status, suggestions

    def auto_calibrate(
        self, config: LevelGenerationConfig, target_rates: Dict[str, float], max_iterations: int = 10
    ) -> LevelGenerationConfig:
        """
        Automatically calibrate level parameters to match target clear rates.

        Args:
            config: Initial level configuration
            target_rates: Target clear rates for each bot type
            max_iterations: Maximum calibration attempts

        Returns:
            Calibrated configuration
        """
        best_config = config
        best_deviation = float('inf')

        print(f"\n🔧 Auto-calibrating level: {config.level_id}")

        for iteration in range(max_iterations):
            # Generate and test level
            level_json = self.generate_level(config)
            actual_rates, status, _ = self.validate_level(level_json, config, iterations=50)

            # Calculate average deviation
            avg_deviation = sum(
                abs(actual_rates.get(bot, 0) - target_rates.get(bot, 0)) * 100
                for bot in target_rates.keys()
            ) / len(target_rates)

            print(f"  Iteration {iteration + 1}: avg deviation = {avg_deviation:.1f}%")

            if avg_deviation < best_deviation:
                best_deviation = avg_deviation
                best_config = config

            # If good enough, stop
            if avg_deviation < 15.0:
                print(f"  ✅ Calibration successful: {avg_deviation:.1f}% deviation")
                break

            # Adjust parameters based on deviation
            avg_actual = sum(actual_rates.values()) / len(actual_rates)
            avg_target = sum(target_rates.values()) / len(target_rates)

            if avg_actual > avg_target + 0.1:
                # Too easy - increase difficulty
                config.tile_count = min(config.tile_count + 9, 150)
                config.tile_types = min(config.tile_types + 1, 12)
                config.max_moves = max(int(config.max_moves * 0.9), 10)
            elif avg_actual < avg_target - 0.1:
                # Too hard - decrease difficulty
                config.tile_count = max(config.tile_count - 9, 9)
                config.tile_types = max(config.tile_types - 1, 3)
                config.max_moves = int(config.max_moves * 1.1)

        return best_config


def get_tier_defaults(tier: DifficultyTier) -> Dict:
    """Get default parameters for each difficulty tier."""
    defaults = {
        DifficultyTier.EASY: {
            "tile_types": 4,
            "tile_count": 36,
            "layers": 1,
            "max_moves": 50,
            "ice_tiles": 0,
            "grass_tiles": 0,
            "link_tiles": 0,
            "target_rates": {
                "novice": 0.95,
                "casual": 0.98,
                "average": 0.99,
                "expert": 1.00,
                "optimal": 1.00,
            }
        },
        DifficultyTier.MEDIUM: {
            "tile_types": 5,
            "tile_count": 45,
            "layers": 2,
            "max_moves": 50,
            "ice_tiles": 0,
            "grass_tiles": 0,
            "link_tiles": 0,
            "target_rates": {
                "novice": 0.30,
                "casual": 0.55,
                "average": 0.75,
                "expert": 0.90,
                "optimal": 0.98,
            }
        },
        DifficultyTier.HARD: {
            "tile_types": 6,
            "tile_count": 60,
            "layers": 3,
            "max_moves": 45,
            "ice_tiles": 0,
            "grass_tiles": 0,
            "link_tiles": 0,
            "target_rates": {
                "novice": 0.10,
                "casual": 0.25,
                "average": 0.50,
                "expert": 0.80,
                "optimal": 0.95,
            }
        },
        DifficultyTier.EXPERT: {
            "tile_types": 10,
            "tile_count": 120,
            "layers": 4,
            "max_moves": 30,
            "ice_tiles": 6,
            "grass_tiles": 4,
            "link_tiles": 4,
            "target_rates": {
                "novice": 0.02,
                "casual": 0.10,
                "average": 0.30,
                "expert": 0.65,
                "optimal": 0.90,
            }
        },
        DifficultyTier.IMPOSSIBLE: {
            "tile_types": 12,
            "tile_count": 150,
            "layers": 4,
            "max_moves": 25,
            "ice_tiles": 10,
            "grass_tiles": 6,
            "link_tiles": 6,
            "target_rates": {
                "novice": 0.00,
                "casual": 0.02,
                "average": 0.10,
                "expert": 0.40,
                "optimal": 0.75,
            }
        }
    }
    return defaults.get(tier, defaults[DifficultyTier.MEDIUM])


def main():
    parser = argparse.ArgumentParser(
        description="Generate benchmark levels with automatic validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--tier",
        choices=["easy", "medium", "hard", "expert", "impossible"],
        help="Difficulty tier for generated levels"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of levels to generate (default: 1)"
    )
    parser.add_argument(
        "--start-id",
        help="Starting level ID (e.g., hard_01)"
    )
    parser.add_argument(
        "--tile-types",
        type=int,
        help="Number of tile types (3-12)"
    )
    parser.add_argument(
        "--layers",
        type=int,
        help="Number of layers (1-4)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated levels with 100 iterations"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Auto-calibrate level parameters to match target clear rates"
    )
    parser.add_argument(
        "--config",
        help="JSON configuration file for level generation"
    )
    parser.add_argument(
        "--output",
        default="generated_levels.json",
        help="Output file for generated levels (default: generated_levels.json)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)"
    )

    args = parser.parse_args()

    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "BENCHMARK LEVEL GENERATOR" + " " * 33 + "║")
    print("╚" + "=" * 78 + "╝")

    generator = LevelGenerator(seed=args.seed)
    generated_levels = []

    # Load configuration
    if args.config:
        with open(args.config, 'r') as f:
            config_data = json.load(f)
        # Generate from config file
        # TODO: Implement config file loading
        print(f"\n❌ Config file loading not yet implemented")
        return 1

    # Generate levels based on CLI arguments
    if not args.tier:
        print("\n❌ Error: --tier is required")
        return 1

    tier = DifficultyTier(args.tier)
    defaults = get_tier_defaults(tier)

    # Override defaults with CLI arguments
    if args.tile_types:
        defaults["tile_types"] = args.tile_types
    if args.layers:
        defaults["layers"] = args.layers

    # Generate levels
    for i in range(args.count):
        level_num = i + 1
        if args.start_id:
            level_id = args.start_id if i == 0 else f"{args.tier}_{level_num:02d}"
        else:
            level_id = f"{args.tier}_{level_num:02d}"

        config = LevelGenerationConfig(
            tier=args.tier,
            level_id=level_id,
            name=f"Generated {args.tier.upper()} #{level_num}",
            description=f"Auto-generated {args.tier} level with {defaults['tile_types']} tile types",
            tags=["generated", f"{defaults['layers']}_layer"],
            tile_types=defaults["tile_types"],
            tile_count=defaults["tile_count"],
            layers=defaults["layers"],
            max_moves=defaults["max_moves"],
            ice_tiles=defaults["ice_tiles"],
            grass_tiles=defaults["grass_tiles"],
            link_tiles=defaults["link_tiles"],
            expected_clear_rates=defaults["target_rates"] if args.validate else None,
            seed=args.seed + i,
        )

        print(f"\n{'=' * 80}")
        print(f"Generating: {config.name} ({level_id})")
        print(f"{'=' * 80}")
        print(f"Tile types: {config.tile_types}, Total tiles: {config.tile_count}, Layers: {config.layers}")

        # Auto-calibrate if requested
        if args.calibrate:
            config = generator.auto_calibrate(config, defaults["target_rates"])

        # Generate level
        level_json = generator.generate_level(config)

        # Validate if requested
        validation_status = "not_validated"
        actual_clear_rates = {}
        suggestions = []

        if args.validate:
            print(f"\n🔍 Validating with 100 iterations...")
            actual_clear_rates, validation_status, suggestions = generator.validate_level(
                level_json, config, iterations=100
            )

            # Print results
            print(f"\nValidation Results:")
            for bot_type in ["novice", "casual", "average", "expert", "optimal"]:
                actual = actual_clear_rates.get(bot_type, 0)
                expected = config.expected_clear_rates.get(bot_type, 0) if config.expected_clear_rates else 0
                deviation = abs(actual - expected) * 100 if config.expected_clear_rates else 0

                status_icon = "✅" if deviation <= 15 else "⚠️" if deviation <= 22.5 else "❌"
                print(f"{status_icon} {bot_type:8s}: Actual {actual:5.1%}, Expected {expected:5.1%}, Deviation {deviation:4.1f}%")

            print(f"\n{'─' * 80}")
            if validation_status == "pass":
                print(f"✅ Level {level_id}: VALIDATION PASSED")
            elif validation_status == "warn":
                print(f"⚠️  Level {level_id}: VALIDATION WARNING")
            else:
                print(f"❌ Level {level_id}: VALIDATION FAILED")

            if suggestions:
                print(f"\n💡 Suggestions:")
                for suggestion in suggestions:
                    print(f"   {suggestion}")

        # Store generated level
        generated_level = GeneratedLevel(
            config=config,
            level_json=level_json,
            actual_clear_rates=actual_clear_rates,
            validation_status=validation_status,
            suggestions=suggestions,
        )
        generated_levels.append(generated_level)

    # Save to file
    output_data = {
        "generator_version": "1.0",
        "generation_date": "2025-12-22",
        "seed": args.seed,
        "levels": [
            {
                "config": asdict(gl.config),
                "level_json": gl.level_json,
                "actual_clear_rates": gl.actual_clear_rates,
                "validation_status": gl.validation_status,
                "suggestions": gl.suggestions,
            }
            for gl in generated_levels
        ]
    }

    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\n{'=' * 80}")
    print(f"GENERATION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Generated {len(generated_levels)} level(s)")
    print(f"Output saved to: {args.output}")

    if args.validate:
        passed = sum(1 for gl in generated_levels if gl.validation_status == "pass")
        warned = sum(1 for gl in generated_levels if gl.validation_status == "warn")
        failed = sum(1 for gl in generated_levels if gl.validation_status == "fail")

        print(f"\nValidation Summary:")
        print(f"  Passed: {passed}/{len(generated_levels)}")
        print(f"  Warnings: {warned}/{len(generated_levels)}")
        print(f"  Failed: {failed}/{len(generated_levels)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
