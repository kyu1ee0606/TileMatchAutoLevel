"""Bot-based level simulation engine with diverse play styles."""
import random
import math
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics

from ..models.bot_profile import BotProfile, BotType, BotTeam, get_profile


@dataclass
class GameState:
    """Represents the current state of a simulated game."""
    tiles: Dict[int, Dict[str, List[Any]]]  # layer_idx -> {pos: tile_data}
    goals_remaining: Dict[str, int]  # goal_type -> count remaining
    moves_used: int = 0
    cleared: bool = False
    max_moves: int = 30
    combo_count: int = 0
    total_tiles_cleared: int = 0


@dataclass
class Move:
    """Represents a possible move in the game."""
    layer_idx: int
    position: str
    tile_type: str
    attribute: str = ""
    score: float = 0.0  # Calculated based on bot profile
    match_count: int = 0  # Number of tiles in this match


@dataclass
class BotSimulationResult:
    """Result from a single bot's simulation runs."""
    bot_type: BotType
    bot_name: str
    iterations: int
    clear_rate: float
    avg_moves: float
    min_moves: int
    max_moves: int
    std_moves: float  # 표준편차
    avg_combo: float
    avg_tiles_cleared: float

    def to_dict(self) -> Dict:
        return {
            "bot_type": self.bot_type.value,
            "bot_name": self.bot_name,
            "iterations": self.iterations,
            "clear_rate": round(self.clear_rate, 4),
            "avg_moves": round(self.avg_moves, 2),
            "min_moves": self.min_moves,
            "max_moves": self.max_moves,
            "std_moves": round(self.std_moves, 2),
            "avg_combo": round(self.avg_combo, 2),
            "avg_tiles_cleared": round(self.avg_tiles_cleared, 2),
        }


@dataclass
class MultiBotAssessmentResult:
    """Aggregated result from multi-bot assessment."""
    bot_results: List[BotSimulationResult]
    overall_difficulty: float  # 0-100 점수
    difficulty_grade: str  # S/A/B/C/D
    target_audience: str  # 추천 대상 플레이어
    difficulty_variance: float  # 봇 간 난이도 차이
    recommended_moves: int  # 권장 이동 횟수
    analysis_summary: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            "bot_results": [r.to_dict() for r in self.bot_results],
            "overall_difficulty": round(self.overall_difficulty, 2),
            "difficulty_grade": self.difficulty_grade,
            "target_audience": self.target_audience,
            "difficulty_variance": round(self.difficulty_variance, 4),
            "recommended_moves": self.recommended_moves,
            "analysis_summary": self.analysis_summary,
        }


class BotSimulator:
    """
    Advanced bot simulator that mimics different player skill levels.

    Each bot type has distinct decision-making characteristics:
    - Novice: Random-like selection, high mistake rate
    - Casual: Basic strategy, occasional mistakes
    - Average: Greedy strategy, rare mistakes
    - Expert: Optimized strategy with lookahead
    - Optimal: MCTS-based perfect play
    """

    MATCHABLE_TYPES = {"t0", "t2", "t4", "t5", "t6", "t10", "t11", "t12", "t14", "t15"}
    OBSTACLE_TYPES = {"t8", "t9"}
    GOAL_TYPES = {"craft_s", "stack_s"}

    def __init__(self):
        self._rng = random.Random()

    def simulate_with_profile(
        self,
        level_json: Dict[str, Any],
        profile: BotProfile,
        iterations: int = 100,
        max_moves: int = 30,
        seed: Optional[int] = None,
    ) -> BotSimulationResult:
        """
        Run simulation with a specific bot profile.

        Args:
            level_json: Level data to simulate
            profile: Bot profile configuration
            iterations: Number of simulation runs
            max_moves: Maximum moves per game
            seed: Random seed for reproducibility

        Returns:
            BotSimulationResult with statistics
        """
        if seed is not None:
            self._rng.seed(seed)

        results: List[GameState] = []

        for i in range(iterations):
            # Use iteration as sub-seed for reproducibility
            if seed is not None:
                self._rng.seed(seed + i)

            state = self._create_initial_state(level_json, max_moves)
            final_state = self._play_game(state, profile)
            results.append(final_state)

        # Calculate statistics
        cleared_count = sum(1 for r in results if r.cleared)
        moves_list = [r.moves_used for r in results]
        combo_list = [r.combo_count for r in results]
        tiles_list = [r.total_tiles_cleared for r in results]

        return BotSimulationResult(
            bot_type=profile.bot_type,
            bot_name=profile.name,
            iterations=iterations,
            clear_rate=cleared_count / iterations if iterations > 0 else 0,
            avg_moves=statistics.mean(moves_list) if moves_list else 0,
            min_moves=min(moves_list) if moves_list else 0,
            max_moves=max(moves_list) if moves_list else max_moves,
            std_moves=statistics.stdev(moves_list) if len(moves_list) > 1 else 0,
            avg_combo=statistics.mean(combo_list) if combo_list else 0,
            avg_tiles_cleared=statistics.mean(tiles_list) if tiles_list else 0,
        )

    def assess_difficulty(
        self,
        level_json: Dict[str, Any],
        team: Optional[BotTeam] = None,
        max_moves: int = 30,
        parallel: bool = True,
        seed: Optional[int] = None,
    ) -> MultiBotAssessmentResult:
        """
        Run multi-bot assessment to determine level difficulty.

        Args:
            level_json: Level data to assess
            team: Bot team configuration (defaults to all bots)
            max_moves: Maximum moves per game
            parallel: Whether to run simulations in parallel
            seed: Random seed for reproducibility

        Returns:
            MultiBotAssessmentResult with comprehensive analysis
        """
        if team is None:
            team = BotTeam.default_team(iterations_per_bot=100)

        bot_results: List[BotSimulationResult] = []

        if parallel and len(team.profiles) > 1:
            # Parallel execution
            with ThreadPoolExecutor(max_workers=min(5, len(team.profiles))) as executor:
                futures = {
                    executor.submit(
                        self.simulate_with_profile,
                        level_json,
                        profile,
                        team.iterations_per_bot,
                        max_moves,
                        seed + i if seed else None,
                    ): profile
                    for i, profile in enumerate(team.profiles)
                }

                for future in as_completed(futures):
                    result = future.result()
                    bot_results.append(result)
        else:
            # Sequential execution
            for i, profile in enumerate(team.profiles):
                result = self.simulate_with_profile(
                    level_json,
                    profile,
                    team.iterations_per_bot,
                    max_moves,
                    seed + i if seed else None,
                )
                bot_results.append(result)

        # Sort results by bot skill level
        bot_results.sort(key=lambda r: BotType.all_types().index(r.bot_type))

        # Calculate aggregated metrics
        return self._aggregate_results(bot_results, team, max_moves)

    def _aggregate_results(
        self,
        bot_results: List[BotSimulationResult],
        team: BotTeam,
        max_moves: int,
    ) -> MultiBotAssessmentResult:
        """Aggregate individual bot results into comprehensive assessment."""

        # Calculate weighted difficulty score
        total_weight = 0
        weighted_difficulty = 0

        for result in bot_results:
            profile = None
            for p in team.profiles:
                if p.bot_type == result.bot_type:
                    profile = p
                    break

            if profile is None:
                continue

            # Convert clear rate to difficulty (lower clear rate = higher difficulty)
            # Also factor in moves used
            bot_difficulty = self._calculate_bot_difficulty(result, max_moves)

            weighted_difficulty += bot_difficulty * profile.weight
            total_weight += profile.weight

        overall_difficulty = (
            weighted_difficulty / total_weight if total_weight > 0 else 50
        )

        # Calculate difficulty variance between bots
        difficulties = [
            self._calculate_bot_difficulty(r, max_moves) for r in bot_results
        ]
        variance = statistics.variance(difficulties) if len(difficulties) > 1 else 0

        # Determine grade
        grade = self._difficulty_to_grade(overall_difficulty)

        # Determine target audience
        target_audience = self._determine_target_audience(bot_results)

        # Calculate recommended moves
        recommended_moves = self._calculate_recommended_moves(bot_results, max_moves)

        # Build analysis summary
        analysis_summary = self._build_analysis_summary(bot_results, overall_difficulty)

        return MultiBotAssessmentResult(
            bot_results=bot_results,
            overall_difficulty=overall_difficulty,
            difficulty_grade=grade,
            target_audience=target_audience,
            difficulty_variance=variance,
            recommended_moves=recommended_moves,
            analysis_summary=analysis_summary,
        )

    def _calculate_bot_difficulty(
        self, result: BotSimulationResult, max_moves: int
    ) -> float:
        """Calculate difficulty score for a single bot."""
        # Base difficulty from clear rate (inverted)
        clear_difficulty = (1 - result.clear_rate) * 60

        # Move efficiency factor (using more moves = harder)
        if result.avg_moves > 0:
            move_factor = min(1.0, result.avg_moves / max_moves)
            move_difficulty = move_factor * 30
        else:
            move_difficulty = 30

        # Variance factor (high variance = inconsistent difficulty)
        variance_factor = min(1.0, result.std_moves / 10) * 10

        return min(100, clear_difficulty + move_difficulty + variance_factor)

    def _difficulty_to_grade(self, score: float) -> str:
        """Convert difficulty score to grade."""
        if score <= 20:
            return "S"  # 매우 쉬움
        elif score <= 40:
            return "A"  # 쉬움
        elif score <= 60:
            return "B"  # 보통
        elif score <= 80:
            return "C"  # 어려움
        else:
            return "D"  # 매우 어려움

    def _determine_target_audience(
        self, bot_results: List[BotSimulationResult]
    ) -> str:
        """Determine recommended target audience based on clear rates."""
        # Find the bot type with clear rate closest to 70%
        target_clear_rate = 0.7

        best_match = None
        best_diff = float('inf')

        for result in bot_results:
            diff = abs(result.clear_rate - target_clear_rate)
            if diff < best_diff:
                best_diff = diff
                best_match = result

        if best_match is None:
            return "Average"

        audience_map = {
            BotType.NOVICE: "초보자 (입문자용)",
            BotType.CASUAL: "캐주얼 플레이어",
            BotType.AVERAGE: "일반 플레이어",
            BotType.EXPERT: "숙련 플레이어",
            BotType.OPTIMAL: "하드코어 플레이어",
        }

        return audience_map.get(best_match.bot_type, "일반 플레이어")

    def _calculate_recommended_moves(
        self, bot_results: List[BotSimulationResult], max_moves: int
    ) -> int:
        """Calculate recommended move count based on Average bot performance."""
        # Find Average bot result
        for result in bot_results:
            if result.bot_type == BotType.AVERAGE:
                # Recommend moves that would give ~80% clear rate
                if result.clear_rate > 0.8:
                    return max(15, int(result.avg_moves * 0.9))
                elif result.clear_rate < 0.6:
                    return min(50, int(result.avg_moves * 1.2))
                else:
                    return int(result.avg_moves)

        # Fallback: use overall average
        if bot_results:
            avg = statistics.mean([r.avg_moves for r in bot_results])
            return int(avg)

        return max_moves

    def _build_analysis_summary(
        self,
        bot_results: List[BotSimulationResult],
        overall_difficulty: float,
    ) -> Dict[str, Any]:
        """Build detailed analysis summary."""
        # Find specific insights
        insights = []

        # Check if too easy for experts
        expert_result = next(
            (r for r in bot_results if r.bot_type == BotType.EXPERT), None
        )
        if expert_result and expert_result.clear_rate > 0.95:
            insights.append("숙련자에게 너무 쉬울 수 있습니다.")

        # Check if too hard for casual
        casual_result = next(
            (r for r in bot_results if r.bot_type == BotType.CASUAL), None
        )
        if casual_result and casual_result.clear_rate < 0.3:
            insights.append("캐주얼 플레이어에게 너무 어려울 수 있습니다.")

        # Check novice vs average gap
        novice_result = next(
            (r for r in bot_results if r.bot_type == BotType.NOVICE), None
        )
        average_result = next(
            (r for r in bot_results if r.bot_type == BotType.AVERAGE), None
        )
        if novice_result and average_result:
            gap = average_result.clear_rate - novice_result.clear_rate
            if gap > 0.5:
                insights.append("초보자와 평균 플레이어 간 난이도 격차가 큽니다.")

        # Build clear rate breakdown
        clear_rates = {
            r.bot_type.value: round(r.clear_rate * 100, 1)
            for r in bot_results
        }

        return {
            "clear_rates_by_bot": clear_rates,
            "insights": insights,
            "difficulty_category": self._categorize_difficulty(overall_difficulty),
            "balance_score": self._calculate_balance_score(bot_results),
        }

    def _categorize_difficulty(self, score: float) -> str:
        """Categorize difficulty with Korean description."""
        if score <= 20:
            return "튜토리얼급"
        elif score <= 40:
            return "쉬운 난이도"
        elif score <= 60:
            return "적정 난이도"
        elif score <= 80:
            return "챌린지급"
        else:
            return "극한 난이도"

    def _calculate_balance_score(
        self, bot_results: List[BotSimulationResult]
    ) -> float:
        """
        Calculate how well-balanced the level is for different skill levels.

        Higher score = better balance across skill levels.
        """
        if len(bot_results) < 2:
            return 1.0

        # Ideal clear rates for each bot type
        ideal_rates = {
            BotType.NOVICE: 0.4,
            BotType.CASUAL: 0.6,
            BotType.AVERAGE: 0.75,
            BotType.EXPERT: 0.9,
            BotType.OPTIMAL: 0.98,
        }

        total_deviation = 0
        count = 0

        for result in bot_results:
            ideal = ideal_rates.get(result.bot_type, 0.7)
            deviation = abs(result.clear_rate - ideal)
            total_deviation += deviation
            count += 1

        if count == 0:
            return 1.0

        avg_deviation = total_deviation / count
        # Convert deviation to score (0 deviation = 1.0 score)
        balance_score = max(0, 1 - avg_deviation * 2)

        return round(balance_score, 2)

    # ===== Game Simulation Logic =====

    def _create_initial_state(
        self, level_json: Dict[str, Any], max_moves: int
    ) -> GameState:
        """Create initial game state from level JSON."""
        num_layers = level_json.get("layer", 8)
        tiles: Dict[int, Dict[str, List[Any]]] = {}
        goals_remaining: Dict[str, int] = {}

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level_json.get(layer_key, {})
            layer_tiles = layer_data.get("tiles", {})

            if layer_tiles:
                tiles[i] = {}
                for pos, tile_data in layer_tiles.items():
                    if isinstance(tile_data, list):
                        tiles[i][pos] = list(tile_data)

                        # Extract goals
                        if tile_data[0] in self.GOAL_TYPES:
                            goal_type = tile_data[0]
                            goal_count = (
                                tile_data[2][0]
                                if len(tile_data) > 2 and tile_data[2]
                                else 1
                            )
                            goals_remaining[goal_type] = (
                                goals_remaining.get(goal_type, 0) + goal_count
                            )

        return GameState(
            tiles=tiles,
            goals_remaining=goals_remaining,
            max_moves=max_moves,
        )

    def _play_game(self, state: GameState, profile: BotProfile) -> GameState:
        """Play through a game with the given bot profile."""
        while state.moves_used < state.max_moves and not self._is_game_over(state):
            moves = self._get_available_moves(state)

            if not moves:
                break

            # Score moves based on profile
            for move in moves:
                move.score = self._score_move_with_profile(move, state, profile)

            # Select move based on profile behavior
            selected_move = self._select_move_with_profile(moves, state, profile)

            if selected_move:
                tiles_cleared = self._apply_move(state, selected_move)
                state.moves_used += 1
                state.total_tiles_cleared += tiles_cleared

                # Track combo
                if tiles_cleared >= 4:
                    state.combo_count += 1

        # Check if all goals are cleared
        state.cleared = all(count <= 0 for count in state.goals_remaining.values())

        return state

    def _score_move_with_profile(
        self, move: Move, state: GameState, profile: BotProfile
    ) -> float:
        """Score a move based on bot profile characteristics."""
        base_score = 1.0

        # Goal priority bonus
        if state.goals_remaining:
            goal_bonus = profile.goal_priority * 2.0
            base_score += goal_bonus

        # Layer blocking awareness - prefer clearing upper layers
        layer_bonus = move.layer_idx * profile.blocking_awareness * 0.3
        base_score += layer_bonus

        # Chain preference - bonus for chain/attribute tiles
        if move.attribute in ("chain", "frog", "link_w", "link_n"):
            attribute_bonus = profile.chain_preference * 1.5
            base_score += attribute_bonus

        # Pattern recognition - bonus for larger matches
        if move.match_count > 3:
            pattern_bonus = (move.match_count - 3) * profile.pattern_recognition * 0.5
            base_score += pattern_bonus

        # Add randomness based on profile (lower skill = more random)
        randomness = (1 - profile.pattern_recognition) * self._rng.random() * 2
        base_score += randomness

        return base_score

    def _select_move_with_profile(
        self,
        moves: List[Move],
        state: GameState,
        profile: BotProfile,
    ) -> Optional[Move]:
        """Select a move based on bot profile."""
        if not moves:
            return None

        # Check for mistake (random wrong choice)
        if self._rng.random() < profile.mistake_rate:
            # Make a suboptimal choice
            return self._rng.choice(moves)

        # Sort by score
        sorted_moves = sorted(moves, key=lambda m: m.score, reverse=True)

        # Apply patience factor (impatient bots might not pick the best)
        if profile.patience < 0.5 and len(sorted_moves) > 1:
            # Might pick 2nd or 3rd best
            cutoff = max(1, int(len(sorted_moves) * profile.patience))
            return self._rng.choice(sorted_moves[:cutoff])

        # Lookahead for higher skill bots
        if profile.lookahead_depth > 0 and len(sorted_moves) > 1:
            # Simplified lookahead: prefer moves that enable more moves
            best_move = sorted_moves[0]
            best_future_moves = self._estimate_future_moves(state, best_move, profile)

            for move in sorted_moves[1:min(3, len(sorted_moves))]:
                future_moves = self._estimate_future_moves(state, move, profile)
                if future_moves > best_future_moves:
                    best_move = move
                    best_future_moves = future_moves

            return best_move

        return sorted_moves[0]

    def _estimate_future_moves(
        self, state: GameState, move: Move, profile: BotProfile
    ) -> int:
        """Estimate number of available moves after making a move."""
        # This is a simplified heuristic
        # In a full implementation, this would do actual lookahead

        # Count remaining tiles of same type as potential matches
        accessible = self._get_accessible_tiles(state)
        same_type_count = sum(
            1 for _, _, t in accessible
            if t[0] == move.tile_type and t[0] in self.MATCHABLE_TYPES
        )

        return same_type_count

    def _is_game_over(self, state: GameState) -> bool:
        """Check if the game is over."""
        if all(count <= 0 for count in state.goals_remaining.values()):
            return True

        for layer_tiles in state.tiles.values():
            for tile_data in layer_tiles.values():
                if tile_data[0] in self.MATCHABLE_TYPES:
                    return False

        return True

    def _get_available_moves(self, state: GameState) -> List[Move]:
        """Get all available moves in the current state."""
        moves = []
        accessible = self._get_accessible_tiles(state)

        # Count tiles by type for matching
        type_counts: Dict[str, int] = {}
        for layer_idx, pos, tile_data in accessible:
            tile_type = tile_data[0]
            if tile_type in self.MATCHABLE_TYPES:
                type_counts[tile_type] = type_counts.get(tile_type, 0) + 1

        for layer_idx, pos, tile_data in accessible:
            tile_type = tile_data[0]
            attribute = tile_data[1] if len(tile_data) > 1 else ""

            if tile_type not in self.MATCHABLE_TYPES:
                continue

            # Need at least 3 tiles of same type
            if type_counts.get(tile_type, 0) >= 3:
                moves.append(Move(
                    layer_idx=layer_idx,
                    position=pos,
                    tile_type=tile_type,
                    attribute=attribute,
                    match_count=type_counts.get(tile_type, 0),
                ))

        return moves

    def _get_accessible_tiles(
        self, state: GameState
    ) -> List[Tuple[int, str, List[Any]]]:
        """Get tiles that are accessible (not blocked by upper layers)."""
        accessible = []
        occupied_positions: Set[str] = set()

        sorted_layers = sorted(state.tiles.keys(), reverse=True)

        for layer_idx in sorted_layers:
            layer_tiles = state.tiles.get(layer_idx, {})

            for pos, tile_data in layer_tiles.items():
                if pos not in occupied_positions:
                    accessible.append((layer_idx, pos, tile_data))
                    occupied_positions.add(pos)

        return accessible

    def _apply_move(self, state: GameState, move: Move) -> int:
        """Apply a move to the game state. Returns number of tiles cleared."""
        layer_tiles = state.tiles.get(move.layer_idx, {})
        tiles_cleared = 0

        if move.position in layer_tiles:
            del layer_tiles[move.position]
            tiles_cleared += 1

            # Progress goals
            for goal_type in state.goals_remaining:
                if state.goals_remaining[goal_type] > 0:
                    state.goals_remaining[goal_type] -= 1
                    break

        # Remove matching tiles (at least 2 more for a 3-match)
        accessible = self._get_accessible_tiles(state)
        removed = 0

        for l_idx, pos, t_data in accessible:
            if t_data[0] == move.tile_type and removed < 2:
                layer = state.tiles.get(l_idx, {})
                if pos in layer:
                    del layer[pos]
                    removed += 1
                    tiles_cleared += 1

        return tiles_cleared


# Singleton instance
_bot_simulator: Optional[BotSimulator] = None


def get_bot_simulator() -> BotSimulator:
    """Get or create bot simulator singleton instance."""
    global _bot_simulator
    if _bot_simulator is None:
        _bot_simulator = BotSimulator()
    return _bot_simulator
