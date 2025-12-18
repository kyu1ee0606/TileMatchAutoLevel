"""Tests for level analyzer."""
import pytest
from app.core.analyzer import LevelAnalyzer, get_analyzer
from app.models.level import DifficultyGrade


@pytest.fixture
def analyzer():
    """Create analyzer instance."""
    return LevelAnalyzer()


@pytest.fixture
def sample_level():
    """Sample level JSON for testing."""
    return {
        "layer": 8,
        "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
        "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_3": {"col": "7", "row": "7", "tiles": {"3_3": ["t0", ""]}, "num": "1"},
        "layer_4": {
            "col": "8",
            "row": "8",
            "tiles": {
                "3_3": ["t0", ""],
                "4_3": ["t11", ""],
                "3_4": ["t12", ""],
                "4_4": ["t0", ""],
            },
            "num": "4",
        },
        "layer_5": {
            "col": "7",
            "row": "7",
            "tiles": {
                "0_0": ["t8", ""],
                "1_0": ["t2", "link_w"],
                "2_0": ["t0", ""],
                "2_2": ["t0", "chain"],
                "4_2": ["t0", ""],
                "5_2": ["t0", ""],
                "6_2": ["t0", "chain"],
            },
            "num": "7",
        },
        "layer_6": {
            "col": "8",
            "row": "8",
            "tiles": {
                "1_1": ["t6", ""],
                "2_1": ["t2", "chain"],
                "5_1": ["t0", "frog"],
                "6_1": ["t0", "chain"],
            },
            "num": "4",
        },
        "layer_7": {
            "col": "7",
            "row": "7",
            "tiles": {
                "0_0": ["t4", ""],
                "1_0": ["t0", ""],
                "2_0": ["t0", "frog"],
                "3_0": ["t5", ""],
                "4_0": ["t2", ""],
                "3_6": ["craft_s", "", [3]],
                "4_6": ["stack_s", "", [6]],
            },
            "num": "7",
        },
    }


@pytest.fixture
def empty_level():
    """Empty level JSON for testing."""
    return {
        "layer": 8,
        "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
        "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_3": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
        "layer_4": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_5": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
        "layer_6": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
        "layer_7": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
    }


class TestLevelAnalyzer:
    """Test cases for LevelAnalyzer."""

    def test_analyze_returns_report(self, analyzer, sample_level):
        """Test that analyze returns a DifficultyReport."""
        report = analyzer.analyze(sample_level)

        assert report is not None
        assert hasattr(report, "score")
        assert hasattr(report, "grade")
        assert hasattr(report, "metrics")
        assert hasattr(report, "recommendations")

    def test_analyze_score_in_range(self, analyzer, sample_level):
        """Test that score is within valid range."""
        report = analyzer.analyze(sample_level)

        assert 0 <= report.score <= 100

    def test_analyze_grade_valid(self, analyzer, sample_level):
        """Test that grade is a valid DifficultyGrade."""
        report = analyzer.analyze(sample_level)

        assert report.grade in DifficultyGrade

    def test_analyze_metrics_complete(self, analyzer, sample_level):
        """Test that all metrics are present."""
        report = analyzer.analyze(sample_level)
        metrics = report.metrics

        assert metrics.total_tiles > 0
        assert metrics.active_layers > 0
        assert isinstance(metrics.chain_count, int)
        assert isinstance(metrics.frog_count, int)
        assert isinstance(metrics.link_count, int)
        assert isinstance(metrics.goal_amount, int)
        assert isinstance(metrics.layer_blocking, float)
        assert isinstance(metrics.tile_types, dict)
        assert isinstance(metrics.goals, list)

    def test_analyze_empty_level(self, analyzer, empty_level):
        """Test analyzing an empty level."""
        report = analyzer.analyze(empty_level)

        assert report.score == 0
        assert report.grade == DifficultyGrade.S
        assert report.metrics.total_tiles == 0
        assert report.metrics.active_layers == 0

    def test_analyze_counts_chain_tiles(self, analyzer, sample_level):
        """Test that chain tiles are counted correctly."""
        report = analyzer.analyze(sample_level)

        # Sample level has chain tiles at: 2_2, 6_2, 2_1, 6_1 = 4 chains
        assert report.metrics.chain_count == 4

    def test_analyze_counts_frog_tiles(self, analyzer, sample_level):
        """Test that frog tiles are counted correctly."""
        report = analyzer.analyze(sample_level)

        # Sample level has frog tiles at: 5_1, 2_0 = 2 frogs
        assert report.metrics.frog_count == 2

    def test_analyze_counts_link_tiles(self, analyzer, sample_level):
        """Test that link tiles are counted correctly."""
        report = analyzer.analyze(sample_level)

        # Sample level has link tiles at: 1_0 = 1 link
        assert report.metrics.link_count == 1

    def test_analyze_extracts_goals(self, analyzer, sample_level):
        """Test that goals are extracted correctly."""
        report = analyzer.analyze(sample_level)

        # Sample level has goals: craft_s (3), stack_s (6)
        assert len(report.metrics.goals) == 2
        assert report.metrics.goal_amount == 9

    def test_analyze_counts_tile_types(self, analyzer, sample_level):
        """Test that tile types are counted."""
        report = analyzer.analyze(sample_level)

        tile_types = report.metrics.tile_types
        assert "t0" in tile_types
        assert tile_types["t0"] > 0

    def test_grade_from_score_s(self):
        """Test grade S for low scores."""
        assert DifficultyGrade.from_score(0) == DifficultyGrade.S
        assert DifficultyGrade.from_score(10) == DifficultyGrade.S
        assert DifficultyGrade.from_score(20) == DifficultyGrade.S

    def test_grade_from_score_a(self):
        """Test grade A for scores 21-40."""
        assert DifficultyGrade.from_score(21) == DifficultyGrade.A
        assert DifficultyGrade.from_score(30) == DifficultyGrade.A
        assert DifficultyGrade.from_score(40) == DifficultyGrade.A

    def test_grade_from_score_b(self):
        """Test grade B for scores 41-60."""
        assert DifficultyGrade.from_score(41) == DifficultyGrade.B
        assert DifficultyGrade.from_score(50) == DifficultyGrade.B
        assert DifficultyGrade.from_score(60) == DifficultyGrade.B

    def test_grade_from_score_c(self):
        """Test grade C for scores 61-80."""
        assert DifficultyGrade.from_score(61) == DifficultyGrade.C
        assert DifficultyGrade.from_score(70) == DifficultyGrade.C
        assert DifficultyGrade.from_score(80) == DifficultyGrade.C

    def test_grade_from_score_d(self):
        """Test grade D for high scores."""
        assert DifficultyGrade.from_score(81) == DifficultyGrade.D
        assert DifficultyGrade.from_score(90) == DifficultyGrade.D
        assert DifficultyGrade.from_score(100) == DifficultyGrade.D

    def test_recommendations_generated(self, analyzer, sample_level):
        """Test that recommendations are generated."""
        report = analyzer.analyze(sample_level)

        # Should have some recommendations based on the level metrics
        assert isinstance(report.recommendations, list)

    def test_singleton_analyzer(self):
        """Test that get_analyzer returns singleton."""
        analyzer1 = get_analyzer()
        analyzer2 = get_analyzer()

        assert analyzer1 is analyzer2

    def test_to_dict_conversion(self, analyzer, sample_level):
        """Test report to_dict conversion."""
        report = analyzer.analyze(sample_level)
        result = report.to_dict()

        assert isinstance(result, dict)
        assert "score" in result
        assert "grade" in result
        assert "metrics" in result
        assert "recommendations" in result
        assert isinstance(result["grade"], str)
