"""Level simulation engine with Monte Carlo methods."""
import random
import statistics
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from ..models.level import SimulationResult


class SimulationStrategy(str, Enum):
    """Simulation strategy enumeration."""
    RANDOM = "random"
    GREEDY = "greedy"
    OPTIMAL = "optimal"


@dataclass
class GameState:
    """Represents the current state of a simulated game."""
    tiles: Dict[int, Dict[str, List[Any]]]  # layer_idx -> {pos: tile_data}
    goals_remaining: Dict[str, int]  # goal_type -> count remaining
    moves_used: int = 0
    cleared: bool = False
    max_moves: int = 30


@dataclass
class Move:
    """Represents a possible move in the game."""
    layer_idx: int
    position: str
    tile_type: str
    score: float = 0.0  # For greedy/optimal strategies


class LevelSimulator:
    """Simulates level play-through with various strategies."""

    # Tile matching rules (simplified)
    MATCHABLE_TYPES = {"t0", "t2", "t4", "t5", "t6", "t10", "t11", "t12", "t14", "t15"}
    OBSTACLE_TYPES = {"t8", "t9"}
    GOAL_TYPES = {"craft_s", "stack_s"}

    def simulate(
        self,
        level_json: Dict[str, Any],
        iterations: int = 500,
        strategy: str = "greedy",
        max_moves: int = 30,
    ) -> SimulationResult:
        """
        Run Monte Carlo simulation on a level.

        Args:
            level_json: Level data to simulate.
            iterations: Number of simulation runs.
            strategy: Strategy to use (random/greedy/optimal).
            max_moves: Maximum moves per simulation.

        Returns:
            SimulationResult with statistics.
        """
        results = []

        for _ in range(iterations):
            state = self._create_initial_state(level_json, max_moves)
            result = self._play_game(state, SimulationStrategy(strategy))
            results.append(result)

        cleared_count = sum(1 for r in results if r.cleared)
        moves_list = [r.moves_used for r in results]

        return SimulationResult(
            clear_rate=cleared_count / len(results),
            avg_moves=statistics.mean(moves_list) if moves_list else 0,
            min_moves=min(moves_list) if moves_list else 0,
            max_moves=max(moves_list) if moves_list else 0,
            iterations=iterations,
            strategy=strategy,
        )

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
                        # Deep copy tile data
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

    def _play_game(self, state: GameState, strategy: SimulationStrategy) -> GameState:
        """Play through a game with the given strategy."""
        while state.moves_used < state.max_moves and not self._is_game_over(state):
            moves = self._get_available_moves(state)

            if not moves:
                break

            if strategy == SimulationStrategy.RANDOM:
                move = random.choice(moves)
            elif strategy == SimulationStrategy.GREEDY:
                move = self._select_greedy_move(moves, state)
            else:  # OPTIMAL - use simple lookahead
                move = self._select_optimal_move(moves, state)

            self._apply_move(state, move)
            state.moves_used += 1

        # Check if all goals are cleared
        state.cleared = all(count <= 0 for count in state.goals_remaining.values())

        return state

    def _is_game_over(self, state: GameState) -> bool:
        """Check if the game is over (all goals cleared or no tiles left)."""
        if all(count <= 0 for count in state.goals_remaining.values()):
            return True

        # Check if there are any playable tiles
        for layer_tiles in state.tiles.values():
            for tile_data in layer_tiles.values():
                if tile_data[0] in self.MATCHABLE_TYPES:
                    return False

        return True

    def _get_available_moves(self, state: GameState) -> List[Move]:
        """Get all available moves in the current state."""
        moves = []

        # Get accessible tiles (top-most tiles at each position)
        accessible = self._get_accessible_tiles(state)

        for layer_idx, pos, tile_data in accessible:
            tile_type = tile_data[0]

            # Skip obstacles and goals
            if tile_type not in self.MATCHABLE_TYPES:
                continue

            # Check if tile can be matched (simplified: any accessible matching tile)
            can_match = self._can_tile_match(state, layer_idx, pos, tile_type)

            if can_match:
                moves.append(Move(
                    layer_idx=layer_idx,
                    position=pos,
                    tile_type=tile_type,
                ))

        return moves

    def _get_accessible_tiles(
        self, state: GameState
    ) -> List[Tuple[int, str, List[Any]]]:
        """Get tiles that are accessible (not blocked by upper layers)."""
        accessible = []
        occupied_positions: Set[str] = set()

        # Start from top layer
        sorted_layers = sorted(state.tiles.keys(), reverse=True)

        for layer_idx in sorted_layers:
            layer_tiles = state.tiles.get(layer_idx, {})

            for pos, tile_data in layer_tiles.items():
                # Check if position is blocked by upper layer tile
                if pos not in occupied_positions:
                    accessible.append((layer_idx, pos, tile_data))
                    occupied_positions.add(pos)

        return accessible

    def _can_tile_match(
        self, state: GameState, layer_idx: int, pos: str, tile_type: str
    ) -> bool:
        """Check if a tile can be matched (simplified matching logic)."""
        # In a real implementation, this would check for adjacent tiles
        # and proper match patterns. For simulation, we use simplified rules.

        # Count accessible tiles of the same type
        same_type_count = 0
        accessible = self._get_accessible_tiles(state)

        for l_idx, p, t_data in accessible:
            if t_data[0] == tile_type:
                same_type_count += 1

        # Need at least 3 tiles of same type to match
        return same_type_count >= 3

    def _select_greedy_move(self, moves: List[Move], state: GameState) -> Move:
        """Select the best move using greedy strategy."""
        # Score moves based on potential impact
        for move in moves:
            move.score = self._score_move(move, state)

        # Sort by score and pick the best
        moves.sort(key=lambda m: m.score, reverse=True)
        return moves[0]

    def _select_optimal_move(self, moves: List[Move], state: GameState) -> Move:
        """Select move using simple lookahead (limited MCTS)."""
        # For simplicity, just use greedy with higher weight on goal progress
        for move in moves:
            move.score = self._score_move(move, state) * 1.5

        moves.sort(key=lambda m: m.score, reverse=True)
        return moves[0]

    def _score_move(self, move: Move, state: GameState) -> float:
        """Score a move based on its potential value."""
        score = 1.0

        # Bonus for matching tiles that progress towards goals
        if state.goals_remaining.get("craft_s", 0) > 0:
            score += 0.5

        # Bonus for higher layer moves (clears blocking tiles)
        score += move.layer_idx * 0.2

        # Bonus for tiles with obstacles (clearing them is valuable)
        layer_tiles = state.tiles.get(move.layer_idx, {})
        tile_data = layer_tiles.get(move.position, [])
        if len(tile_data) > 1 and tile_data[1] in ("chain", "frog"):
            score += 1.0

        return score

    def _apply_move(self, state: GameState, move: Move) -> None:
        """Apply a move to the game state."""
        layer_tiles = state.tiles.get(move.layer_idx, {})

        if move.position in layer_tiles:
            tile_data = layer_tiles[move.position]
            tile_type = tile_data[0]

            # Remove the tile
            del layer_tiles[move.position]

            # Progress goals (simplified)
            for goal_type in state.goals_remaining:
                if state.goals_remaining[goal_type] > 0:
                    state.goals_remaining[goal_type] -= 1
                    break

        # Remove matching tiles (simplified: remove 2 more of same type)
        accessible = self._get_accessible_tiles(state)
        removed = 0

        for l_idx, pos, t_data in accessible:
            if t_data[0] == move.tile_type and removed < 2:
                layer = state.tiles.get(l_idx, {})
                if pos in layer:
                    del layer[pos]
                    removed += 1


# Singleton instance
_simulator = None


def get_simulator() -> LevelSimulator:
    """Get or create simulator singleton instance."""
    global _simulator
    if _simulator is None:
        _simulator = LevelSimulator()
    return _simulator
