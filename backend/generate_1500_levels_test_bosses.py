#!/usr/bin/env python3
"""
1500 레벨 톱니바퀴식 생성 및 보스레벨 일괄 테스트

- 1500개 레벨을 톱니바퀴 난이도 곡선으로 생성
- 보스레벨(10의 배수: 10, 20, ..., 1500)만 추출하여 검증
- 마일스톤 보스(100의 배수)는 추가 검증
"""

import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.generator import LevelGenerator
from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile
from app.models.level import GenerationParams
from app.models.leveling_config import (
    get_complete_level_config,
    calculate_level_difficulty,
    get_unlocked_gimmicks,
    is_milestone_level,
    PROFESSIONAL_GIMMICK_UNLOCK,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants
TOTAL_LEVELS = 1500
BOSS_CYCLE = 10  # 보스 레벨 주기
MILESTONE_CYCLE = 100  # 마일스톤 보스 주기
BOT_TEST_ITERATIONS = 30  # 봇 시뮬레이션 반복 횟수
MAX_WORKERS = 8  # 병렬 처리 워커 수


@dataclass
class LevelResult:
    """레벨 생성 결과"""
    level_number: int
    level_json: Dict
    target_difficulty: float
    actual_difficulty: float
    grade: str
    gimmicks: List[str]
    is_boss: bool
    is_milestone: bool
    generation_time: float


@dataclass
class BossTestResult:
    """보스 레벨 테스트 결과"""
    level_number: int
    is_milestone: bool
    target_difficulty: float
    actual_difficulty: float
    grade: str
    novice_clear_rate: float
    casual_clear_rate: float
    average_clear_rate: float
    expert_clear_rate: float
    optimal_clear_rate: float
    avg_moves: float
    test_passed: bool
    failure_reason: str = ""


def generate_level_with_config(
    generator: LevelGenerator,
    level_number: int,
    config: Dict[str, Any]
) -> LevelResult:
    """레벨 설정으로 레벨 생성"""
    start_time = time.time()

    # 레벨 설정에서 파라미터 추출
    target_difficulty = config['difficulty']
    gimmicks = config['gimmicks']
    layer_count = config['layer_count']
    tile_count = config['tile_count']
    tile_types_count = config['tile_types_count']

    # 타일 타입 선택 (t0 제외)
    all_tile_types = ['t1', 't2', 't3', 't4', 't5']
    tile_types = all_tile_types[:tile_types_count]

    # Goals 설정 (craft/stack이 언락된 경우에만)
    goals = []
    if 'craft' in gimmicks and level_number >= 195:
        goals.append({'type': 'craft', 'direction': 's', 'count': 3})
    if 'stack' in gimmicks and level_number >= 215:
        goals.append({'type': 'stack', 'direction': 'e', 'count': 3})

    # 장애물 타입 필터링 (craft, stack 제외)
    obstacle_types = [g for g in gimmicks if g not in ['craft', 'stack']]

    params = GenerationParams(
        target_difficulty=target_difficulty,
        grid_size=(7, 7),
        max_layers=layer_count,
        tile_types=tile_types,
        obstacle_types=obstacle_types if obstacle_types else [],
        goals=goals if goals else [],
    )

    result = generator.generate(params)
    generation_time = time.time() - start_time

    return LevelResult(
        level_number=level_number,
        level_json=result.level_json,
        target_difficulty=target_difficulty,
        actual_difficulty=result.actual_difficulty,
        grade=result.grade,
        gimmicks=gimmicks,
        is_boss=(level_number % BOSS_CYCLE == 0),
        is_milestone=is_milestone_level(level_number),
        generation_time=generation_time
    )


def test_boss_level(
    simulator: BotSimulator,
    level_result: LevelResult,
    iterations: int = BOT_TEST_ITERATIONS
) -> BossTestResult:
    """보스 레벨 테스트"""
    bot_results = {}

    for bot_type in BotType:
        profile = get_profile(bot_type)
        sim_result = simulator.simulate_with_profile(
            level_result.level_json,
            profile,
            iterations=iterations,
            max_moves=200,
            seed=42
        )
        bot_results[bot_type.value] = {
            'clear_rate': sim_result.clear_rate,
            'avg_moves': sim_result.avg_moves,
        }

    # 검증 기준
    # - optimal 봇은 최소 70% 이상 클리어해야 함
    # - average 봇은 최소 30% 이상 클리어해야 함
    optimal_rate = bot_results['optimal']['clear_rate']
    average_rate = bot_results['average']['clear_rate']

    test_passed = True
    failure_reason = ""

    if optimal_rate < 0.70:
        test_passed = False
        failure_reason = f"Optimal 봇 클리어율 부족: {optimal_rate*100:.1f}% < 70%"
    elif average_rate < 0.20:
        test_passed = False
        failure_reason = f"Average 봇 클리어율 부족: {average_rate*100:.1f}% < 20%"

    return BossTestResult(
        level_number=level_result.level_number,
        is_milestone=level_result.is_milestone,
        target_difficulty=level_result.target_difficulty,
        actual_difficulty=level_result.actual_difficulty,
        grade=level_result.grade,
        novice_clear_rate=bot_results['novice']['clear_rate'],
        casual_clear_rate=bot_results['casual']['clear_rate'],
        average_clear_rate=bot_results['average']['clear_rate'],
        expert_clear_rate=bot_results['expert']['clear_rate'],
        optimal_clear_rate=bot_results['optimal']['clear_rate'],
        avg_moves=bot_results['optimal']['avg_moves'],
        test_passed=test_passed,
        failure_reason=failure_reason
    )


def generate_levels_batch(
    generator: LevelGenerator,
    start_level: int,
    end_level: int,
    progress_callback=None
) -> List[LevelResult]:
    """레벨 배치 생성"""
    results = []

    for level_num in range(start_level, end_level + 1):
        try:
            # 레벨 설정 가져오기
            config = get_complete_level_config(level_num, use_sawtooth=True)

            # 레벨 생성
            result = generate_level_with_config(generator, level_num, config)
            results.append(result)

            if progress_callback:
                progress_callback(level_num, result)

        except Exception as e:
            logger.error(f"레벨 {level_num} 생성 실패: {e}")

    return results


def main():
    print("=" * 70)
    print("1500 레벨 톱니바퀴식 생성 및 보스레벨 테스트")
    print("=" * 70)
    print()

    # Initialize
    generator = LevelGenerator()
    simulator = BotSimulator()

    all_levels: List[LevelResult] = []
    boss_levels: List[LevelResult] = []
    milestone_levels: List[LevelResult] = []

    # ========================================
    # Phase 1: 1500 레벨 생성
    # ========================================
    print(f"[Phase 1] 1500 레벨 생성 (톱니바퀴 난이도)")
    print("-" * 70)

    total_start = time.time()
    batch_size = 100

    for batch_start in range(1, TOTAL_LEVELS + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, TOTAL_LEVELS)
        batch_start_time = time.time()

        logger.info(f"레벨 {batch_start}-{batch_end} 생성 중...")

        def progress_cb(level_num, result):
            if level_num % 50 == 0:
                logger.info(f"  레벨 {level_num} 완료 (난이도: {result.actual_difficulty:.2f}, 등급: {result.grade})")

        batch_results = generate_levels_batch(
            generator, batch_start, batch_end, progress_cb
        )

        all_levels.extend(batch_results)

        # 보스레벨 분류
        for result in batch_results:
            if result.is_boss:
                boss_levels.append(result)
                if result.is_milestone:
                    milestone_levels.append(result)

        batch_time = time.time() - batch_start_time
        logger.info(f"  배치 완료: {len(batch_results)}개 ({batch_time:.1f}초)")

    gen_time = time.time() - total_start

    print()
    print(f"생성 완료!")
    print(f"  - 총 레벨: {len(all_levels)}개")
    print(f"  - 보스레벨: {len(boss_levels)}개 (10의 배수)")
    print(f"  - 마일스톤 보스: {len(milestone_levels)}개 (100의 배수)")
    print(f"  - 소요 시간: {gen_time:.1f}초")
    print()

    # ========================================
    # Phase 2: 보스레벨 테스트
    # ========================================
    print(f"[Phase 2] 보스레벨 일괄 테스트 ({len(boss_levels)}개)")
    print("-" * 70)

    test_start = time.time()
    test_results: List[BossTestResult] = []

    for i, boss in enumerate(boss_levels):
        logger.info(f"보스레벨 {boss.level_number} 테스트 중... ({i+1}/{len(boss_levels)})")

        try:
            result = test_boss_level(simulator, boss)
            test_results.append(result)

            status = "✓ PASS" if result.test_passed else "✗ FAIL"
            milestone_mark = "🏆" if result.is_milestone else ""

            logger.info(
                f"  {status} {milestone_mark} "
                f"난이도: {result.actual_difficulty:.2f} ({result.grade}), "
                f"Optimal: {result.optimal_clear_rate*100:.0f}%, "
                f"Average: {result.average_clear_rate*100:.0f}%"
            )

            if not result.test_passed:
                logger.warning(f"    실패 원인: {result.failure_reason}")

        except Exception as e:
            logger.error(f"  테스트 실패: {e}")

    test_time = time.time() - test_start

    # ========================================
    # Phase 3: 결과 분석
    # ========================================
    print()
    print(f"[Phase 3] 결과 분석")
    print("=" * 70)

    passed = [r for r in test_results if r.test_passed]
    failed = [r for r in test_results if not r.test_passed]

    print(f"\n📊 테스트 결과 요약")
    print(f"  - 통과: {len(passed)}/{len(test_results)} ({len(passed)/len(test_results)*100:.1f}%)")
    print(f"  - 실패: {len(failed)}/{len(test_results)} ({len(failed)/len(test_results)*100:.1f}%)")
    print(f"  - 소요 시간: {test_time:.1f}초")

    # 등급별 분포
    print(f"\n📈 등급별 분포 (보스레벨)")
    grade_counts = {}
    for r in test_results:
        grade_counts[r.grade] = grade_counts.get(r.grade, 0) + 1

    for grade in ['S', 'A', 'B', 'C', 'D']:
        count = grade_counts.get(grade, 0)
        bar = '█' * (count // 3)
        print(f"  {grade}: {count:3d} {bar}")

    # 마일스톤 보스 결과
    print(f"\n🏆 마일스톤 보스 결과 (100의 배수)")
    milestone_results = [r for r in test_results if r.is_milestone]
    for r in milestone_results:
        status = "✓" if r.test_passed else "✗"
        print(f"  Level {r.level_number:4d}: {status} "
              f"난이도 {r.actual_difficulty:.2f} ({r.grade}), "
              f"Optimal {r.optimal_clear_rate*100:.0f}%")

    # 실패한 레벨 상세
    if failed:
        print(f"\n⚠️ 실패한 보스레벨 상세")
        for r in failed[:20]:  # 최대 20개만 표시
            print(f"  Level {r.level_number}: {r.failure_reason}")
        if len(failed) > 20:
            print(f"  ... 외 {len(failed)-20}개")

    # 난이도 구간별 클리어율
    print(f"\n📉 난이도 구간별 평균 클리어율")
    tiers = [
        ('S등급 (0.0-0.2)', 0.0, 0.2),
        ('A등급 (0.2-0.4)', 0.2, 0.4),
        ('B등급 (0.4-0.6)', 0.4, 0.6),
        ('C등급 (0.6-0.8)', 0.6, 0.8),
        ('D등급 (0.8-1.0)', 0.8, 1.0),
    ]

    for tier_name, low, high in tiers:
        tier_results = [r for r in test_results if low <= r.actual_difficulty < high]
        if tier_results:
            avg_optimal = sum(r.optimal_clear_rate for r in tier_results) / len(tier_results)
            avg_average = sum(r.average_clear_rate for r in tier_results) / len(tier_results)
            avg_casual = sum(r.casual_clear_rate for r in tier_results) / len(tier_results)
            print(f"  {tier_name}: {len(tier_results):3d}개")
            print(f"    Optimal: {avg_optimal*100:5.1f}%, Average: {avg_average*100:5.1f}%, Casual: {avg_casual*100:5.1f}%")

    # ========================================
    # Phase 4: 결과 저장
    # ========================================
    output_dir = Path(__file__).parent / "test_results"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 보스레벨 JSON 저장
    boss_data = {
        'timestamp': timestamp,
        'total_levels': TOTAL_LEVELS,
        'boss_count': len(boss_levels),
        'milestone_count': len(milestone_levels),
        'test_passed': len(passed),
        'test_failed': len(failed),
        'generation_time_sec': gen_time,
        'test_time_sec': test_time,
        'boss_levels': [
            {
                'level_number': b.level_number,
                'level_json': b.level_json,
                'target_difficulty': b.target_difficulty,
                'actual_difficulty': b.actual_difficulty,
                'grade': b.grade,
                'gimmicks': b.gimmicks,
                'is_milestone': b.is_milestone,
            }
            for b in boss_levels
        ],
        'test_results': [
            {
                'level_number': r.level_number,
                'is_milestone': r.is_milestone,
                'target_difficulty': r.target_difficulty,
                'actual_difficulty': r.actual_difficulty,
                'grade': r.grade,
                'novice_clear_rate': r.novice_clear_rate,
                'casual_clear_rate': r.casual_clear_rate,
                'average_clear_rate': r.average_clear_rate,
                'expert_clear_rate': r.expert_clear_rate,
                'optimal_clear_rate': r.optimal_clear_rate,
                'avg_moves': r.avg_moves,
                'test_passed': r.test_passed,
                'failure_reason': r.failure_reason,
            }
            for r in test_results
        ]
    }

    output_file = output_dir / f"boss_levels_1500_{timestamp}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(boss_data, f, indent=2, ensure_ascii=False)

    print(f"\n💾 결과 저장: {output_file}")

    # 전체 레벨 JSON 저장 (압축)
    all_levels_file = output_dir / f"all_1500_levels_{timestamp}.json"
    all_levels_data = {
        'timestamp': timestamp,
        'total_levels': len(all_levels),
        'levels': [
            {
                'level_number': l.level_number,
                'level_json': l.level_json,
                'target_difficulty': l.target_difficulty,
                'actual_difficulty': l.actual_difficulty,
                'grade': l.grade,
                'gimmicks': l.gimmicks,
                'is_boss': l.is_boss,
                'is_milestone': l.is_milestone,
            }
            for l in all_levels
        ]
    }

    with open(all_levels_file, 'w', encoding='utf-8') as f:
        json.dump(all_levels_data, f, ensure_ascii=False)

    print(f"💾 전체 레벨 저장: {all_levels_file}")

    # ========================================
    # 최종 요약
    # ========================================
    print()
    print("=" * 70)
    print("최종 요약")
    print("=" * 70)
    print(f"총 레벨 생성: {len(all_levels)}개")
    print(f"보스레벨 테스트: {len(test_results)}개")
    print(f"테스트 통과율: {len(passed)/len(test_results)*100:.1f}%")
    print(f"마일스톤 보스 통과: {len([r for r in milestone_results if r.test_passed])}/{len(milestone_results)}")
    print(f"총 소요 시간: {gen_time + test_time:.1f}초")
    print()

    if len(failed) == 0:
        print("🎉 모든 보스레벨 테스트 통과!")
    else:
        print(f"⚠️ {len(failed)}개 보스레벨 테스트 실패 - 결과 파일 확인 필요")


if __name__ == "__main__":
    main()
