"""Level difficulty analyzer engine."""
from typing import Dict, List, Any, Set, Tuple
from ..models.level import (
    LevelMetrics,
    DifficultyReport,
    DifficultyGrade,
    ATTRIBUTES,
)


class LevelAnalyzer:
    """Analyzes level difficulty based on various metrics."""

    # Weight configuration for difficulty calculation
    # Score is normalized to 0-100 by dividing by 3.0
    # Target ranges: Easy 0-30, Medium 30-60, Hard 60-100
    WEIGHTS = {
        "total_tiles": 0.5,       # 30-120 tiles → 15-60 points
        "active_layers": 4.0,     # 3-8 layers → 12-32 points
        "chain_count": 5.0,       # 0-15 chains → 0-75 points (increased from 3.0)
        "frog_count": 6.0,        # 0-10 frogs → 0-60 points (increased from 4.0)
        "link_count": 3.0,        # 0-10 links → 0-30 points (increased from 2.0)
        "ice_count": 4.0,         # 0-15 ice → 0-60 points (increased from 2.5)
        "goal_amount": 1.5,       # 3-10 goals → 4.5-15 points
        "layer_blocking": 0.15,   # Reduced: blocking can be 0-300 → 0-45 points
    }

    # Recommendation thresholds
    THRESHOLDS = {
        "chain_high": 12,
        "chain_low": 3,
        "frog_high": 8,
        "frog_low": 2,
        "goal_high": 12,
        "goal_low": 3,
        "layer_blocking_high": 10,
        "tiles_high": 120,
        "tiles_low": 30,
    }

    def analyze(self, level_json: Dict[str, Any]) -> DifficultyReport:
        """
        Analyze a level and return a difficulty report.

        Args:
            level_json: The level JSON data to analyze.

        Returns:
            DifficultyReport with score, grade, metrics, and recommendations.
        """
        metrics = self._extract_metrics(level_json)
        score = self._calculate_score(metrics)
        grade = DifficultyGrade.from_score(score)
        recommendations = self._generate_recommendations(metrics)

        return DifficultyReport(
            score=score,
            grade=grade,
            metrics=metrics,
            recommendations=recommendations,
        )

    def _extract_metrics(self, level_json: Dict[str, Any]) -> LevelMetrics:
        """Extract all metrics from level JSON."""
        total_tiles = 0
        active_layers = 0
        chain_count = 0
        frog_count = 0
        link_count = 0
        ice_count = 0
        goal_amount = 0
        tile_types: Dict[str, int] = {}
        goals: List[Dict[str, Any]] = []
        layer_positions: Dict[int, Set[str]] = {}

        num_layers = level_json.get("layer", 8)

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level_json.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            if tiles:
                active_layers += 1
                layer_positions[i] = set(tiles.keys())

                for pos, tile_data in tiles.items():
                    if not isinstance(tile_data, list) or len(tile_data) < 2:
                        continue

                    tile_type = tile_data[0]
                    attribute = tile_data[1] if len(tile_data) > 1 else ""
                    extra = tile_data[2] if len(tile_data) > 2 else None

                    total_tiles += 1

                    # Count tile types
                    tile_types[tile_type] = tile_types.get(tile_type, 0) + 1

                    # Count attributes
                    if attribute == "chain":
                        chain_count += 1
                    elif attribute == "frog":
                        frog_count += 1
                    elif attribute == "ice":
                        ice_count += 1
                    elif attribute.startswith("link_"):
                        link_count += 1

                    # Extract goals (support all direction variants: s, n, e, w)
                    if tile_type.startswith(("craft_", "stack_")):
                        count = extra[0] if extra and len(extra) > 0 else 1
                        goals.append({"type": tile_type, "count": count})
                        goal_amount += count

        # Calculate layer blocking score
        layer_blocking = self._calculate_layer_blocking(layer_positions, num_layers)

        return LevelMetrics(
            total_tiles=total_tiles,
            active_layers=active_layers,
            chain_count=chain_count,
            frog_count=frog_count,
            link_count=link_count,
            ice_count=ice_count,
            goal_amount=goal_amount,
            layer_blocking=layer_blocking,
            tile_types=tile_types,
            goals=goals,
        )

    def _calculate_layer_blocking(
        self, layer_positions: Dict[int, Set[str]], num_layers: int
    ) -> float:
        """
        Calculate how much upper layers block lower layers.

        Higher layers blocking lower layers increases difficulty.
        """
        blocking_score = 0.0

        for upper_layer in range(num_layers - 1, 0, -1):
            upper_positions = layer_positions.get(upper_layer, set())

            for lower_layer in range(upper_layer - 1, -1, -1):
                lower_positions = layer_positions.get(lower_layer, set())

                # Check for overlapping positions
                overlap = upper_positions & lower_positions

                # Weight by layer difference (higher layers blocking = more impact)
                layer_weight = (num_layers - upper_layer) * 0.5
                blocking_score += len(overlap) * layer_weight

        return blocking_score

    def _calculate_score(self, metrics: LevelMetrics) -> float:
        """Calculate difficulty score from metrics."""
        score = 0.0

        score += metrics.total_tiles * self.WEIGHTS["total_tiles"]
        score += metrics.active_layers * self.WEIGHTS["active_layers"]
        score += metrics.chain_count * self.WEIGHTS["chain_count"]
        score += metrics.frog_count * self.WEIGHTS["frog_count"]
        score += metrics.link_count * self.WEIGHTS["link_count"]
        score += metrics.ice_count * self.WEIGHTS["ice_count"]
        score += metrics.goal_amount * self.WEIGHTS["goal_amount"]
        score += metrics.layer_blocking * self.WEIGHTS["layer_blocking"]

        # Normalize to 0-100 range
        normalized_score = score / 3.0
        return min(100.0, max(0.0, normalized_score))

    def _generate_recommendations(self, metrics: LevelMetrics) -> List[str]:
        """Generate recommendations based on metrics."""
        recommendations = []

        # Chain recommendations
        if metrics.chain_count > self.THRESHOLDS["chain_high"]:
            recommendations.append(
                f"체인 타일이 {metrics.chain_count}개로 많습니다. "
                f"{self.THRESHOLDS['chain_high'] - 2}~{self.THRESHOLDS['chain_high']}개로 줄이면 적절합니다."
            )
        elif metrics.chain_count < self.THRESHOLDS["chain_low"] and metrics.chain_count > 0:
            recommendations.append(
                f"체인 타일이 {metrics.chain_count}개로 적습니다. "
                "난이도를 높이려면 더 추가하세요."
            )

        # Frog recommendations
        if metrics.frog_count > self.THRESHOLDS["frog_high"]:
            recommendations.append(
                f"개구리 장애물이 {metrics.frog_count}개로 매우 많습니다. "
                f"{self.THRESHOLDS['frog_high'] - 2}개 이하로 줄이는 것을 권장합니다."
            )
        elif metrics.frog_count > self.THRESHOLDS["frog_high"] // 2:
            recommendations.append(
                f"개구리 장애물이 {metrics.frog_count}개로 상당히 많습니다."
            )

        # Goal recommendations
        if metrics.goal_amount > self.THRESHOLDS["goal_high"]:
            recommendations.append(
                f"목표 수집량({metrics.goal_amount})이 높습니다. "
                "이동 횟수와 균형을 확인하세요."
            )
        elif metrics.goal_amount < self.THRESHOLDS["goal_low"]:
            recommendations.append(
                f"목표 수집량({metrics.goal_amount})이 낮습니다. "
                "레벨이 너무 쉬울 수 있습니다."
            )

        # Layer blocking recommendations
        if metrics.layer_blocking > self.THRESHOLDS["layer_blocking_high"]:
            recommendations.append(
                "상위 레이어가 하위 레이어를 많이 가리고 있습니다. "
                "플레이어가 답답함을 느낄 수 있습니다."
            )

        # Total tiles recommendations
        if metrics.total_tiles > self.THRESHOLDS["tiles_high"]:
            recommendations.append(
                f"총 타일 수({metrics.total_tiles})가 많습니다. "
                "플레이 시간이 길어질 수 있습니다."
            )
        elif metrics.total_tiles < self.THRESHOLDS["tiles_low"]:
            recommendations.append(
                f"총 타일 수({metrics.total_tiles})가 적습니다. "
                "레벨이 너무 짧을 수 있습니다."
            )

        # Active layers recommendations
        if metrics.active_layers < 3:
            recommendations.append(
                f"활성 레이어가 {metrics.active_layers}개로 적습니다. "
                "더 많은 레이어를 활용하면 난이도를 높일 수 있습니다."
            )

        # Link tiles recommendations
        if metrics.link_count > 0:
            recommendations.append(
                f"링크 타일이 {metrics.link_count}개 있습니다. "
                "연결된 타일은 동시에 처리해야 하므로 전략적 배치가 중요합니다."
            )

        return recommendations


# Singleton instance
_analyzer = None


def get_analyzer() -> LevelAnalyzer:
    """Get or create analyzer singleton instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = LevelAnalyzer()
    return _analyzer
