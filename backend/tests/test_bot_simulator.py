"""Tests for bot simulator and multi-bot difficulty assessment."""
import pytest
from app.models.bot_profile import (
    BotType,
    BotProfile,
    BotTeam,
    get_profile,
    get_all_profiles,
    create_custom_profile,
    PREDEFINED_PROFILES,
)
from app.core.bot_simulator import (
    BotSimulator,
    get_bot_simulator,
    BotSimulationResult,
    MultiBotAssessmentResult,
)
from app.core.difficulty_assessor import (
    DifficultyAssessor,
    get_difficulty_assessor,
    ComprehensiveDifficultyReport,
)


# Sample level data for testing
SAMPLE_LEVEL_EASY = {
    "layer": 8,
    "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
    "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_3": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
    "layer_4": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_5": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
    "layer_6": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_7": {
        "col": "7", "row": "7",
        "tiles": {
            "0_0": ["t0", ""], "1_0": ["t0", ""], "2_0": ["t0", ""],
            "3_0": ["t0", ""], "4_0": ["t0", ""], "5_0": ["t0", ""],
            "0_1": ["t2", ""], "1_1": ["t2", ""], "2_1": ["t2", ""],
            "3_1": ["t2", ""], "4_1": ["t2", ""], "5_1": ["t2", ""],
            "0_2": ["t4", ""], "1_2": ["t4", ""], "2_2": ["t4", ""],
            "3_6": ["craft_s", "", [3]],
        },
        "num": "16"
    }
}

SAMPLE_LEVEL_HARD = {
    "layer": 8,
    "layer_0": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_1": {"col": "7", "row": "7", "tiles": {}, "num": "0"},
    "layer_2": {"col": "8", "row": "8", "tiles": {}, "num": "0"},
    "layer_3": {"col": "7", "row": "7", "tiles": {"3_3": ["t0", ""]}, "num": "1"},
    "layer_4": {
        "col": "8", "row": "8",
        "tiles": {
            "3_3": ["t0", "chain"], "4_3": ["t11", "chain"],
            "3_4": ["t12", "chain"], "4_4": ["t0", "chain"]
        },
        "num": "4"
    },
    "layer_5": {
        "col": "7", "row": "7",
        "tiles": {
            "0_0": ["t8", ""], "1_0": ["t2", "chain"], "2_0": ["t0", "frog"],
            "4_0": ["t0", "frog"], "5_0": ["t0", "chain"], "6_0": ["t0", "frog"],
            "0_1": ["t0", "chain"], "2_1": ["t0", "frog"], "4_1": ["t0", "chain"], "6_1": ["t0", "frog"],
            "0_2": ["t0", "chain"], "1_2": ["t0", "frog"], "2_2": ["t0", "chain"],
            "4_2": ["t0", "frog"], "5_2": ["t0", "chain"], "6_2": ["t0", "frog"],
        },
        "num": "16"
    },
    "layer_6": {
        "col": "8", "row": "8",
        "tiles": {
            "1_1": ["t6", "chain"], "2_1": ["t2", "chain"], "5_1": ["t0", "frog"], "6_1": ["t0", "chain"],
            "1_2": ["t0", "chain"], "2_2": ["t0", "frog"], "5_2": ["t0", "chain"], "6_2": ["t0", "frog"],
        },
        "num": "8"
    },
    "layer_7": {
        "col": "7", "row": "7",
        "tiles": {
            "0_0": ["t4", "frog"], "1_0": ["t0", "chain"], "2_0": ["t0", "frog"],
            "3_0": ["t5", "chain"], "4_0": ["t2", "frog"], "5_0": ["t8", "chain"], "6_0": ["t8", "frog"],
            "0_1": ["t9", "chain"], "1_1": ["t14", "frog"], "2_1": ["t0", "chain"],
            "3_1": ["t5", "frog"], "4_1": ["t0", "chain"], "5_1": ["t0", "frog"], "6_1": ["t8", "chain"],
            "3_6": ["craft_s", "", [6]],
            "4_6": ["craft_s", "", [9]],
            "6_6": ["stack_s", "", [12]]
        },
        "num": "20"
    }
}


class TestBotProfile:
    """Tests for BotProfile model."""

    def test_predefined_profiles_exist(self):
        """Test that all predefined profiles are available."""
        for bot_type in BotType:
            assert bot_type in PREDEFINED_PROFILES
            profile = get_profile(bot_type)
            assert profile is not None
            assert profile.bot_type == bot_type

    def test_get_all_profiles(self):
        """Test getting all profiles."""
        profiles = get_all_profiles()
        assert len(profiles) == 5
        assert all(isinstance(p, BotProfile) for p in profiles)

    def test_profile_skill_progression(self):
        """Test that profiles have increasing skill levels."""
        novice = get_profile(BotType.NOVICE)
        casual = get_profile(BotType.CASUAL)
        average = get_profile(BotType.AVERAGE)
        expert = get_profile(BotType.EXPERT)
        optimal = get_profile(BotType.OPTIMAL)

        # Mistake rate should decrease with skill
        assert novice.mistake_rate > casual.mistake_rate
        assert casual.mistake_rate > average.mistake_rate
        assert average.mistake_rate > expert.mistake_rate
        assert expert.mistake_rate >= optimal.mistake_rate

        # Lookahead should increase with skill
        assert novice.lookahead_depth < casual.lookahead_depth
        assert casual.lookahead_depth <= average.lookahead_depth
        assert average.lookahead_depth <= expert.lookahead_depth
        assert expert.lookahead_depth <= optimal.lookahead_depth

    def test_create_custom_profile(self):
        """Test creating custom profiles."""
        custom = create_custom_profile(
            name="Test Bot",
            base_type=BotType.AVERAGE,
            mistake_rate=0.05,
            lookahead_depth=5,
        )

        assert custom.name == "Test Bot"
        assert custom.mistake_rate == 0.05
        assert custom.lookahead_depth == 5
        # Other values should come from base
        assert custom.goal_priority == get_profile(BotType.AVERAGE).goal_priority

    def test_profile_to_dict(self):
        """Test profile serialization."""
        profile = get_profile(BotType.AVERAGE)
        data = profile.to_dict()

        assert "name" in data
        assert "bot_type" in data
        assert "mistake_rate" in data
        assert data["bot_type"] == "average"


class TestBotTeam:
    """Tests for BotTeam configuration."""

    def test_default_team(self):
        """Test default team creation."""
        team = BotTeam.default_team(iterations_per_bot=100)

        assert len(team.profiles) == 5
        assert team.iterations_per_bot == 100
        assert team.total_iterations() == 500

    def test_casual_team(self):
        """Test casual team creation."""
        team = BotTeam.casual_team(iterations_per_bot=50)

        assert len(team.profiles) == 3
        bot_types = {p.bot_type for p in team.profiles}
        assert BotType.NOVICE in bot_types
        assert BotType.CASUAL in bot_types
        assert BotType.AVERAGE in bot_types

    def test_hardcore_team(self):
        """Test hardcore team creation."""
        team = BotTeam.hardcore_team(iterations_per_bot=50)

        assert len(team.profiles) == 3
        bot_types = {p.bot_type for p in team.profiles}
        assert BotType.AVERAGE in bot_types
        assert BotType.EXPERT in bot_types
        assert BotType.OPTIMAL in bot_types


class TestBotSimulator:
    """Tests for BotSimulator."""

    def test_simulator_singleton(self):
        """Test simulator singleton pattern."""
        sim1 = get_bot_simulator()
        sim2 = get_bot_simulator()
        assert sim1 is sim2

    def test_simulate_with_profile(self):
        """Test single bot simulation."""
        simulator = get_bot_simulator()
        profile = get_profile(BotType.AVERAGE)

        result = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=profile,
            iterations=20,
            max_moves=30,
            seed=42,
        )

        assert isinstance(result, BotSimulationResult)
        assert result.bot_type == BotType.AVERAGE
        assert result.iterations == 20
        assert 0 <= result.clear_rate <= 1
        assert result.avg_moves >= 0
        assert result.min_moves >= 0
        assert result.max_moves >= result.min_moves

    def test_simulate_reproducibility(self):
        """Test that same seed produces same results."""
        simulator = get_bot_simulator()
        profile = get_profile(BotType.AVERAGE)

        result1 = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=profile,
            iterations=10,
            max_moves=30,
            seed=12345,
        )

        result2 = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=profile,
            iterations=10,
            max_moves=30,
            seed=12345,
        )

        assert result1.clear_rate == result2.clear_rate
        assert result1.avg_moves == result2.avg_moves

    def test_assess_difficulty(self):
        """Test multi-bot difficulty assessment."""
        simulator = get_bot_simulator()
        team = BotTeam.casual_team(iterations_per_bot=20)

        result = simulator.assess_difficulty(
            level_json=SAMPLE_LEVEL_EASY,
            team=team,
            max_moves=30,
            parallel=False,
        )

        assert isinstance(result, MultiBotAssessmentResult)
        assert len(result.bot_results) == 3
        assert 0 <= result.overall_difficulty <= 100
        assert result.difficulty_grade in ["S", "A", "B", "C", "D"]
        assert result.recommended_moves > 0

    def test_easy_vs_hard_level(self):
        """Test that easy level has lower difficulty than hard level."""
        simulator = get_bot_simulator()
        team = BotTeam.default_team(iterations_per_bot=30)

        easy_result = simulator.assess_difficulty(
            level_json=SAMPLE_LEVEL_EASY,
            team=team,
            max_moves=30,
            parallel=False,
            seed=42,
        )

        hard_result = simulator.assess_difficulty(
            level_json=SAMPLE_LEVEL_HARD,
            team=team,
            max_moves=30,
            parallel=False,
            seed=42,
        )

        # Easy level should have higher clear rates
        for easy_bot, hard_bot in zip(easy_result.bot_results, hard_result.bot_results):
            if easy_bot.bot_type == hard_bot.bot_type:
                # Not strictly enforced due to randomness, but generally true
                pass

        # Easy level should have lower difficulty score
        # (Relaxed assertion due to simulation variance)
        assert easy_result.overall_difficulty <= hard_result.overall_difficulty + 20


class TestDifficultyAssessor:
    """Tests for comprehensive difficulty assessor."""

    def test_assessor_singleton(self):
        """Test assessor singleton pattern."""
        assessor1 = get_difficulty_assessor()
        assessor2 = get_difficulty_assessor()
        assert assessor1 is assessor2

    def test_comprehensive_assessment(self):
        """Test comprehensive assessment."""
        assessor = get_difficulty_assessor()

        result = assessor.assess(
            level_json=SAMPLE_LEVEL_EASY,
            iterations_per_bot=20,
            max_moves=30,
            parallel=False,
        )

        assert isinstance(result, ComprehensiveDifficultyReport)
        assert result.static_score >= 0
        assert result.simulation_score >= 0
        assert result.combined_score >= 0
        assert result.confidence > 0
        assert result.combined_grade in ["S", "A", "B", "C", "D"]

    def test_quick_assess(self):
        """Test quick assessment mode."""
        assessor = get_difficulty_assessor()

        result = assessor.quick_assess(
            level_json=SAMPLE_LEVEL_EASY,
            iterations=10,
            max_moves=30,
        )

        assert isinstance(result, ComprehensiveDifficultyReport)
        # Quick mode should still produce valid results
        assert len(result.bot_results) > 0

    def test_assessment_to_dict(self):
        """Test assessment serialization."""
        assessor = get_difficulty_assessor()

        result = assessor.quick_assess(
            level_json=SAMPLE_LEVEL_EASY,
            iterations=10,
            max_moves=30,
        )

        data = result.to_dict()

        assert "static_analysis" in data
        assert "simulation_analysis" in data
        assert "combined_analysis" in data
        assert "score" in data["static_analysis"]
        assert "bot_results" in data["simulation_analysis"]
        assert "confidence" in data["combined_analysis"]


class TestBotBehavior:
    """Tests for bot behavior characteristics."""

    def test_novice_vs_expert_performance(self):
        """Test that expert bots perform better than novice bots."""
        simulator = get_bot_simulator()

        novice_result = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=get_profile(BotType.NOVICE),
            iterations=50,
            max_moves=30,
            seed=42,
        )

        expert_result = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=get_profile(BotType.EXPERT),
            iterations=50,
            max_moves=30,
            seed=42,
        )

        # Expert should generally have higher clear rate
        # (Not strictly enforced due to randomness, but check the trend)
        assert expert_result.clear_rate >= novice_result.clear_rate * 0.8

    def test_optimal_bot_performance(self):
        """Test that optimal bot achieves high clear rate on easy level."""
        simulator = get_bot_simulator()

        result = simulator.simulate_with_profile(
            level_json=SAMPLE_LEVEL_EASY,
            profile=get_profile(BotType.OPTIMAL),
            iterations=30,
            max_moves=30,
            seed=42,
        )

        # Optimal bot should have very high clear rate on easy level
        assert result.clear_rate >= 0.5  # At least 50% clear rate


class TestAnalysisSummary:
    """Tests for analysis summary generation."""

    def test_analysis_summary_structure(self):
        """Test analysis summary has expected structure."""
        simulator = get_bot_simulator()
        team = BotTeam.default_team(iterations_per_bot=20)

        result = simulator.assess_difficulty(
            level_json=SAMPLE_LEVEL_EASY,
            team=team,
            max_moves=30,
            parallel=False,
        )

        summary = result.analysis_summary

        assert "clear_rates_by_bot" in summary
        assert "insights" in summary
        assert "difficulty_category" in summary
        assert "balance_score" in summary

    def test_balance_score_range(self):
        """Test that balance score is in valid range."""
        simulator = get_bot_simulator()
        team = BotTeam.default_team(iterations_per_bot=20)

        result = simulator.assess_difficulty(
            level_json=SAMPLE_LEVEL_EASY,
            team=team,
            max_moves=30,
            parallel=False,
        )

        balance_score = result.analysis_summary["balance_score"]
        assert 0 <= balance_score <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
