"""Level difficulty analyzer engine."""
from typing import Dict, List, Any, Set, Tuple
from ..models.level import (
    LevelMetrics,
    DifficultyReport,
    DifficultyGrade,
    ATTRIBUTES,
)
from ..models.gimmick_profile import GIMMICK_DIFFICULTY_WEIGHTS


class LevelAnalyzer:
    """Analyzes level difficulty based on various metrics."""

    # Base weight for gimmick score calculation
    # 기믹 개수에 GIMMICK_DIFFICULTY_WEIGHTS를 곱한 후 이 값을 곱함
    GIMMICK_BASE_WEIGHT = 4.0

    # Weight configuration for difficulty calculation
    # Score is normalized to 0-100 by dividing by 3.0
    # Target ranges: Easy 0-30, Medium 30-60, Hard 60-100
    WEIGHTS = {
        "total_tiles": 0.5,       # 30-120 tiles → 15-60 points
        "active_layers": 4.0,     # 3-8 layers → 12-32 points
        "goal_amount": 1.5,       # 3-10 goals → 4.5-15 points
        "layer_blocking": 0.15,   # Reduced: blocking can be 0-300 → 0-45 points
        # New weights for better bot simulation correlation
        "tile_type_count": 8.0,   # 3-6 types → 24-48 points (덱 큐 막힘 확률에 큰 영향)
        "move_ratio": 15.0,       # 1.5-4.0 ratio → 22.5-60 points (무브 여유도)
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
        goal_amount = 0
        tile_types: Dict[str, int] = {}
        goals: List[Dict[str, Any]] = []
        layer_positions: Dict[int, Set[str]] = {}

        # 모든 기믹 카운트 초기화
        gimmick_counts: Dict[str, int] = {
            "chain": 0,
            "grass": 0,
            "ice": 0,
            "link": 0,
            "frog": 0,
            "bomb": 0,
            "curtain": 0,
            "teleport": 0,
            "unknown": 0,
        }

        num_layers = level_json.get("layer", 8)
        max_moves = level_json.get("max_moves", 30)  # 기본값 30

        # key 기믹 체크 (레벨 필드에서)
        unlock_tile = level_json.get("unlockTile", 0)
        has_key_gimmick = unlock_tile > 0

        # time_attack 기믹 체크 (레벨 필드에서)
        time_attack = level_json.get("timea", 0)
        has_time_attack = time_attack > 0

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

                    # Count all gimmick attributes
                    if attribute:
                        if attribute == "chain":
                            gimmick_counts["chain"] += 1
                        elif attribute == "frog":
                            gimmick_counts["frog"] += 1
                        elif attribute == "ice" or attribute.startswith("ice_"):
                            gimmick_counts["ice"] += 1
                        elif attribute == "grass" or attribute.startswith("grass_"):
                            gimmick_counts["grass"] += 1
                        elif attribute.startswith("link_"):
                            gimmick_counts["link"] += 1
                        elif attribute == "bomb" or attribute.startswith("bomb_"):
                            gimmick_counts["bomb"] += 1
                        elif attribute == "curtain" or attribute.startswith("curtain_"):
                            gimmick_counts["curtain"] += 1
                        elif attribute == "teleport":
                            gimmick_counts["teleport"] += 1
                        elif attribute == "unknown":
                            gimmick_counts["unknown"] += 1

                    # Extract goals (support all direction variants: s, n, e, w)
                    if tile_type.startswith(("craft_", "stack_")):
                        count = extra[0] if extra and len(extra) > 0 else 1
                        goals.append({"type": tile_type, "count": count})
                        goal_amount += count

        # Calculate layer blocking score
        layer_blocking = self._calculate_layer_blocking(layer_positions, num_layers)

        # Calculate new metrics
        tile_type_count = len([t for t in tile_types.keys() if t.startswith("t")])  # t1~t15만 카운트
        move_ratio = total_tiles / max_moves if max_moves > 0 else 0.0

        return LevelMetrics(
            total_tiles=total_tiles,
            active_layers=active_layers,
            chain_count=gimmick_counts["chain"],
            frog_count=gimmick_counts["frog"],
            link_count=gimmick_counts["link"],
            ice_count=gimmick_counts["ice"],
            goal_amount=goal_amount,
            layer_blocking=layer_blocking,
            tile_types=tile_types,
            goals=goals,
            tile_type_count=tile_type_count,
            max_moves=max_moves,
            move_ratio=move_ratio,
            # 추가 기믹 카운트 (확장 필드로 저장)
            grass_count=gimmick_counts["grass"],
            bomb_count=gimmick_counts["bomb"],
            curtain_count=gimmick_counts["curtain"],
            teleport_count=gimmick_counts["teleport"],
            unknown_count=gimmick_counts["unknown"],
            has_key_gimmick=has_key_gimmick,
            has_time_attack=has_time_attack,
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

    def _calculate_gimmick_score(self, metrics: LevelMetrics) -> float:
        """Calculate weighted gimmick difficulty score using unified weights."""
        score = 0.0

        # 기본 기믹들 (LevelMetrics에 직접 있는 필드)
        gimmick_data = {
            "chain": metrics.chain_count,
            "frog": metrics.frog_count,
            "link": metrics.link_count,
            "ice": metrics.ice_count,
        }

        # 확장 기믹들 (hasattr로 안전하게 접근)
        if hasattr(metrics, 'grass_count'):
            gimmick_data["grass"] = metrics.grass_count
        if hasattr(metrics, 'bomb_count'):
            gimmick_data["bomb"] = metrics.bomb_count
        if hasattr(metrics, 'curtain_count'):
            gimmick_data["curtain"] = metrics.curtain_count
        if hasattr(metrics, 'teleport_count'):
            gimmick_data["teleport"] = metrics.teleport_count
        if hasattr(metrics, 'unknown_count'):
            gimmick_data["unknown"] = metrics.unknown_count

        # key와 time_attack은 개수가 아닌 존재 여부로 계산
        if hasattr(metrics, 'has_key_gimmick') and metrics.has_key_gimmick:
            # key 기믹이 있으면 가중치 적용 (1개로 간주)
            score += GIMMICK_DIFFICULTY_WEIGHTS.get("key", 1.0) * self.GIMMICK_BASE_WEIGHT
        if hasattr(metrics, 'has_time_attack') and metrics.has_time_attack:
            # time_attack 기믹이 있으면 가중치 적용 (1개로 간주)
            score += GIMMICK_DIFFICULTY_WEIGHTS.get("time_attack", 1.0) * self.GIMMICK_BASE_WEIGHT

        # 각 기믹에 통합 가중치 적용
        for gimmick_name, count in gimmick_data.items():
            if count > 0:
                weight = GIMMICK_DIFFICULTY_WEIGHTS.get(gimmick_name, 1.0)
                score += count * weight * self.GIMMICK_BASE_WEIGHT

        return score

    def _calculate_score(self, metrics: LevelMetrics) -> float:
        """Calculate difficulty score from metrics."""
        score = 0.0

        score += metrics.total_tiles * self.WEIGHTS["total_tiles"]
        score += metrics.active_layers * self.WEIGHTS["active_layers"]
        score += metrics.goal_amount * self.WEIGHTS["goal_amount"]
        score += metrics.layer_blocking * self.WEIGHTS["layer_blocking"]

        # 통합 기믹 가중치 시스템 사용
        score += self._calculate_gimmick_score(metrics)

        # 타일 종류 다양성: 3종류 기준, 초과 시 급격히 어려워짐
        tile_type_penalty = max(0, metrics.tile_type_count - 3)
        score += tile_type_penalty * self.WEIGHTS["tile_type_count"]

        # 무브 여유도: 비율 2.0 기준, 초과 시 어려움 증가
        move_ratio_penalty = max(0, metrics.move_ratio - 2.0)
        score += move_ratio_penalty * self.WEIGHTS["move_ratio"]

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

        # 추가 기믹 권장사항
        bomb_count = getattr(metrics, 'bomb_count', 0)
        if bomb_count > 5:
            recommendations.append(
                f"폭탄이 {bomb_count}개로 많습니다. "
                "시간 압박이 심해 스트레스를 줄 수 있습니다."
            )

        frog_count = metrics.frog_count
        if frog_count > 0 and metrics.total_tiles < 50:
            recommendations.append(
                "개구리와 적은 타일 수 조합은 매우 어려울 수 있습니다."
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
