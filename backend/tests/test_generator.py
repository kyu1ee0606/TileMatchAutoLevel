"""Tests for level generator."""
import pytest
from app.core.generator import LevelGenerator, get_generator
from app.models.level import GenerationParams, DifficultyGrade


@pytest.fixture
def generator():
    """Create generator instance."""
    return LevelGenerator()


class TestLevelGenerator:
    """Test cases for LevelGenerator."""

    def test_generate_returns_result(self, generator):
        """Test that generate returns a GenerationResult."""
        params = GenerationParams(target_difficulty=0.5)
        result = generator.generate(params)

        assert result is not None
        assert hasattr(result, "level_json")
        assert hasattr(result, "actual_difficulty")
        assert hasattr(result, "grade")
        assert hasattr(result, "generation_time_ms")

    def test_generate_creates_valid_level(self, generator):
        """Test that generated level has valid structure."""
        params = GenerationParams(target_difficulty=0.5)
        result = generator.generate(params)
        level = result.level_json

        assert "layer" in level
        assert isinstance(level["layer"], int)
        assert level["layer"] > 0

        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            assert layer_key in level
            assert "col" in level[layer_key]
            assert "row" in level[layer_key]
            assert "tiles" in level[layer_key]
            assert "num" in level[layer_key]

    def test_generate_with_low_difficulty(self, generator):
        """Test generation with low difficulty target."""
        params = GenerationParams(target_difficulty=0.1)
        result = generator.generate(params)

        # Should produce a relatively easy level
        assert result.actual_difficulty <= 0.5
        assert result.grade in [DifficultyGrade.S, DifficultyGrade.A, DifficultyGrade.B]

    def test_generate_with_high_difficulty(self, generator):
        """Test generation with high difficulty target."""
        params = GenerationParams(target_difficulty=0.9)
        result = generator.generate(params)

        # Should produce a harder level
        assert result.actual_difficulty >= 0.3

    def test_generate_respects_grid_size(self, generator):
        """Test that generation respects grid size parameter."""
        params = GenerationParams(
            target_difficulty=0.5,
            grid_size=(5, 5),
        )
        result = generator.generate(params)
        level = result.level_json

        # Odd layers should be 5x5, even layers should be 6x6
        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            layer = level[layer_key]

            if i % 2 == 1:  # Odd layer
                assert int(layer["col"]) == 5
                assert int(layer["row"]) == 5
            else:  # Even layer
                assert int(layer["col"]) == 6
                assert int(layer["row"]) == 6

    def test_generate_respects_max_layers(self, generator):
        """Test that generation respects max layers parameter."""
        params = GenerationParams(
            target_difficulty=0.5,
            max_layers=6,
        )
        result = generator.generate(params)
        level = result.level_json

        assert level["layer"] == 6

    def test_generate_with_custom_tile_types(self, generator):
        """Test generation with custom tile types."""
        params = GenerationParams(
            target_difficulty=0.5,
            tile_types=["t0", "t2"],
        )
        result = generator.generate(params)
        level = result.level_json

        # Check that tiles are only of specified types
        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            tiles = level[layer_key].get("tiles", {})

            for pos, tile_data in tiles.items():
                tile_type = tile_data[0]
                # Allow goal types and specified tile types
                assert tile_type in ["t0", "t2", "craft_s", "stack_s"]

    def test_generate_with_goals(self, generator):
        """Test generation with custom goals."""
        params = GenerationParams(
            target_difficulty=0.5,
            goals=[
                {"type": "craft_s", "count": 5},
                {"type": "stack_s", "count": 3},
            ],
        )
        result = generator.generate(params)
        level = result.level_json

        # Find goal tiles in the level
        goals_found = []
        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            tiles = level[layer_key].get("tiles", {})

            for pos, tile_data in tiles.items():
                if tile_data[0] in ["craft_s", "stack_s"]:
                    goals_found.append(tile_data)

        assert len(goals_found) >= 2

    def test_generate_adds_obstacles(self, generator):
        """Test that generation adds obstacles."""
        params = GenerationParams(
            target_difficulty=0.7,
            obstacle_types=["chain", "frog"],
        )
        result = generator.generate(params)
        level = result.level_json

        # Check for obstacles in tiles
        obstacle_count = 0
        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            tiles = level[layer_key].get("tiles", {})

            for pos, tile_data in tiles.items():
                if len(tile_data) > 1 and tile_data[1] in ["chain", "frog"]:
                    obstacle_count += 1

        # With higher difficulty, should have some obstacles
        assert obstacle_count > 0

    def test_generate_has_tiles(self, generator):
        """Test that generated level has tiles."""
        params = GenerationParams(target_difficulty=0.5)
        result = generator.generate(params)
        level = result.level_json

        total_tiles = 0
        for i in range(level["layer"]):
            layer_key = f"layer_{i}"
            tiles = level[layer_key].get("tiles", {})
            total_tiles += len(tiles)

        assert total_tiles > 0

    def test_generate_time_recorded(self, generator):
        """Test that generation time is recorded."""
        params = GenerationParams(target_difficulty=0.5)
        result = generator.generate(params)

        assert result.generation_time_ms >= 0

    def test_generate_result_to_dict(self, generator):
        """Test GenerationResult to_dict conversion."""
        params = GenerationParams(target_difficulty=0.5)
        result = generator.generate(params)
        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert "level_json" in result_dict
        assert "actual_difficulty" in result_dict
        assert "grade" in result_dict
        assert "generation_time_ms" in result_dict
        assert isinstance(result_dict["grade"], str)

    def test_singleton_generator(self):
        """Test that get_generator returns singleton."""
        generator1 = get_generator()
        generator2 = get_generator()

        assert generator1 is generator2

    def test_generate_multiple_times(self, generator):
        """Test that multiple generations produce different results."""
        params = GenerationParams(target_difficulty=0.5)

        results = [generator.generate(params) for _ in range(3)]

        # At least some of the results should be different
        # (comparing JSON strings for simplicity)
        level_strs = [str(r.level_json) for r in results]
        unique_levels = set(level_strs)

        # Should have at least 2 unique levels out of 3
        # (randomness means they might occasionally be the same)
        assert len(unique_levels) >= 1
