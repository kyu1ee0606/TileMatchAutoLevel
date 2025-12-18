"""
Unified Difficulty Assessor - Combines static analysis with multi-bot simulation.

This module provides a comprehensive difficulty assessment by:
1. Running static analysis (metrics-based)
2. Running multi-bot simulation
3. Combining both for a holistic difficulty score
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from .analyzer import get_analyzer, LevelAnalyzer
from .bot_simulator import (
    get_bot_simulator,
    BotSimulator,
    MultiBotAssessmentResult,
    BotSimulationResult,
)
from ..models.bot_profile import BotTeam, BotType, get_all_profiles
from ..models.level import DifficultyGrade, DifficultyReport


@dataclass
class ComprehensiveDifficultyReport:
    """
    Comprehensive difficulty report combining static and simulation analysis.
    """
    # Static analysis
    static_score: float
    static_grade: str
    static_metrics: Dict[str, Any]
    static_recommendations: List[str]

    # Simulation analysis
    simulation_score: float
    simulation_grade: str
    bot_results: List[Dict[str, Any]]
    target_audience: str
    recommended_moves: int

    # Combined analysis
    combined_score: float
    combined_grade: str
    confidence: float  # How confident we are in the assessment
    difficulty_breakdown: Dict[str, float]
    final_recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "static_analysis": {
                "score": round(self.static_score, 2),
                "grade": self.static_grade,
                "metrics": self.static_metrics,
                "recommendations": self.static_recommendations,
            },
            "simulation_analysis": {
                "score": round(self.simulation_score, 2),
                "grade": self.simulation_grade,
                "bot_results": self.bot_results,
                "target_audience": self.target_audience,
                "recommended_moves": self.recommended_moves,
            },
            "combined_analysis": {
                "score": round(self.combined_score, 2),
                "grade": self.combined_grade,
                "confidence": round(self.confidence, 2),
                "difficulty_breakdown": {
                    k: round(v, 2) for k, v in self.difficulty_breakdown.items()
                },
                "recommendations": self.final_recommendations,
            },
        }


class DifficultyAssessor:
    """
    Comprehensive difficulty assessor combining multiple analysis methods.

    Analysis Methods:
    1. Static Analysis: Metrics-based analysis of level structure
    2. Simulation Analysis: Multi-bot Monte Carlo simulation
    3. Combined Analysis: Weighted combination with confidence scoring
    """

    # Weight configuration for combining analyses
    WEIGHTS = {
        "static": 0.3,      # 30% weight for static analysis
        "simulation": 0.7,  # 70% weight for simulation
    }

    def __init__(
        self,
        analyzer: Optional[LevelAnalyzer] = None,
        simulator: Optional[BotSimulator] = None,
    ):
        self.analyzer = analyzer or get_analyzer()
        self.simulator = simulator or get_bot_simulator()

    def assess(
        self,
        level_json: Dict[str, Any],
        team: Optional[BotTeam] = None,
        iterations_per_bot: int = 100,
        max_moves: int = 30,
        parallel: bool = True,
    ) -> ComprehensiveDifficultyReport:
        """
        Perform comprehensive difficulty assessment.

        Args:
            level_json: Level data to assess
            team: Bot team for simulation (defaults to all bots)
            iterations_per_bot: Iterations per bot in simulation
            max_moves: Maximum moves in simulation
            parallel: Whether to run simulations in parallel

        Returns:
            ComprehensiveDifficultyReport with all analysis results
        """
        # 1. Static Analysis
        static_report = self.analyzer.analyze(level_json)

        # 2. Simulation Analysis
        if team is None:
            team = BotTeam.default_team(iterations_per_bot=iterations_per_bot)
        else:
            team.iterations_per_bot = iterations_per_bot

        simulation_result = self.simulator.assess_difficulty(
            level_json=level_json,
            team=team,
            max_moves=max_moves,
            parallel=parallel,
        )

        # 3. Combined Analysis
        combined_result = self._combine_analyses(
            static_report, simulation_result
        )

        return combined_result

    def quick_assess(
        self,
        level_json: Dict[str, Any],
        iterations: int = 50,
        max_moves: int = 30,
    ) -> ComprehensiveDifficultyReport:
        """
        Quick assessment with reduced iterations for faster results.

        Good for real-time feedback during level editing.
        """
        # Use only 3 bots for quick assessment
        team = BotTeam.casual_team(iterations_per_bot=iterations)

        return self.assess(
            level_json=level_json,
            team=team,
            iterations_per_bot=iterations,
            max_moves=max_moves,
            parallel=True,
        )

    def detailed_assess(
        self,
        level_json: Dict[str, Any],
        iterations: int = 500,
        max_moves: int = 30,
    ) -> ComprehensiveDifficultyReport:
        """
        Detailed assessment with high iteration count for accuracy.

        Good for final difficulty validation before publishing.
        """
        team = BotTeam.default_team(iterations_per_bot=iterations)

        return self.assess(
            level_json=level_json,
            team=team,
            iterations_per_bot=iterations,
            max_moves=max_moves,
            parallel=True,
        )

    def _combine_analyses(
        self,
        static_report: DifficultyReport,
        simulation_result: MultiBotAssessmentResult,
    ) -> ComprehensiveDifficultyReport:
        """Combine static and simulation analyses into comprehensive report."""

        # Calculate combined score
        combined_score = (
            static_report.score * self.WEIGHTS["static"] +
            simulation_result.overall_difficulty * self.WEIGHTS["simulation"]
        )

        # Calculate confidence based on agreement between methods
        score_diff = abs(static_report.score - simulation_result.overall_difficulty)
        # If both methods agree, confidence is high
        confidence = max(0.5, 1.0 - (score_diff / 100))

        # Adjust confidence based on simulation variance
        if simulation_result.difficulty_variance > 200:
            confidence *= 0.8  # High variance = lower confidence

        # Determine combined grade
        combined_grade = self._score_to_grade(combined_score)

        # Build difficulty breakdown
        difficulty_breakdown = {
            "static_contribution": static_report.score * self.WEIGHTS["static"],
            "simulation_contribution": (
                simulation_result.overall_difficulty * self.WEIGHTS["simulation"]
            ),
            "static_raw": static_report.score,
            "simulation_raw": simulation_result.overall_difficulty,
        }

        # Generate final recommendations
        final_recommendations = self._generate_combined_recommendations(
            static_report, simulation_result, combined_score
        )

        return ComprehensiveDifficultyReport(
            static_score=static_report.score,
            static_grade=static_report.grade.value,
            static_metrics=static_report.metrics.to_dict(),
            static_recommendations=static_report.recommendations,
            simulation_score=simulation_result.overall_difficulty,
            simulation_grade=simulation_result.difficulty_grade,
            bot_results=[r.to_dict() for r in simulation_result.bot_results],
            target_audience=simulation_result.target_audience,
            recommended_moves=simulation_result.recommended_moves,
            combined_score=combined_score,
            combined_grade=combined_grade,
            confidence=confidence,
            difficulty_breakdown=difficulty_breakdown,
            final_recommendations=final_recommendations,
        )

    def _score_to_grade(self, score: float) -> str:
        """Convert score to grade."""
        if score <= 20:
            return "S"
        elif score <= 40:
            return "A"
        elif score <= 60:
            return "B"
        elif score <= 80:
            return "C"
        else:
            return "D"

    def _generate_combined_recommendations(
        self,
        static_report: DifficultyReport,
        simulation_result: MultiBotAssessmentResult,
        combined_score: float,
    ) -> List[str]:
        """Generate final recommendations based on all analyses."""
        recommendations = []

        # Score discrepancy check
        score_diff = abs(static_report.score - simulation_result.overall_difficulty)
        if score_diff > 20:
            if static_report.score > simulation_result.overall_difficulty:
                recommendations.append(
                    "⚠️ 정적 분석보다 실제 플레이가 쉽습니다. "
                    "장애물 배치를 확인하세요."
                )
            else:
                recommendations.append(
                    "⚠️ 정적 분석보다 실제 플레이가 어렵습니다. "
                    "레이어 블로킹 패턴을 확인하세요."
                )

        # Clear rate based recommendations
        avg_clear_rate = 0
        casual_clear_rate = 0
        expert_clear_rate = 0

        for result in simulation_result.bot_results:
            if result.bot_type == BotType.AVERAGE:
                avg_clear_rate = result.clear_rate
            elif result.bot_type == BotType.CASUAL:
                casual_clear_rate = result.clear_rate
            elif result.bot_type == BotType.EXPERT:
                expert_clear_rate = result.clear_rate

        # Balance recommendations
        if avg_clear_rate < 0.5:
            recommendations.append(
                f"📉 평균 플레이어 클리어율이 낮습니다 ({avg_clear_rate*100:.0f}%). "
                "난이도를 낮추는 것을 권장합니다."
            )
        elif avg_clear_rate > 0.9:
            recommendations.append(
                f"📈 평균 플레이어 클리어율이 높습니다 ({avg_clear_rate*100:.0f}%). "
                "챌린지를 원하면 난이도를 높이세요."
            )

        # Skill gap check
        if expert_clear_rate > 0 and casual_clear_rate > 0:
            gap = expert_clear_rate - casual_clear_rate
            if gap > 0.4:
                recommendations.append(
                    "🎯 숙련자와 캐주얼 플레이어 간 격차가 큽니다. "
                    "힌트 시스템 또는 보조 아이템을 고려하세요."
                )

        # Target audience recommendation
        recommendations.append(
            f"👥 추천 대상: {simulation_result.target_audience}"
        )

        # Move count recommendation
        recommendations.append(
            f"⏱️ 권장 이동 횟수: {simulation_result.recommended_moves}회"
        )

        # Add relevant static recommendations (limit to 3)
        static_recs = static_report.recommendations[:3]
        recommendations.extend(static_recs)

        return recommendations


# Singleton instance
_assessor: Optional[DifficultyAssessor] = None


def get_difficulty_assessor() -> DifficultyAssessor:
    """Get or create difficulty assessor singleton instance."""
    global _assessor
    if _assessor is None:
        _assessor = DifficultyAssessor()
    return _assessor
