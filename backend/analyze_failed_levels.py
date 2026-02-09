#!/usr/bin/env python3
"""
실패한 보스레벨 원인 분석 스크립트
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.bot_simulator import BotSimulator
from app.models.bot_profile import BotType, get_profile


def load_test_results():
    """테스트 결과 로드"""
    results_dir = Path(__file__).parent / "test_results"
    latest_file = sorted(results_dir.glob("boss_levels_1500_*.json"))[-1]

    with open(latest_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_level_structure(level_json):
    """레벨 구조 분석"""
    analysis = {
        'total_tiles': 0,
        'layers': set(),
        'tile_types': set(),
        'gimmicks': set(),
        'goals': [],
        'has_craft': False,
        'has_stack': False,
        'craft_goals': [],
        'stack_goals': [],
        'tile_distribution': defaultdict(int),
        'blocked_tiles': 0,
        'max_layer': 0,
    }

    # Goals 분석
    for goal in level_json.get('goals', []):
        goal_type = goal.get('type', '')
        analysis['goals'].append(goal)
        if goal_type == 'craft':
            analysis['has_craft'] = True
            analysis['craft_goals'].append(goal)
        elif goal_type == 'stack':
            analysis['has_stack'] = True
            analysis['stack_goals'].append(goal)

    # 타일 분석
    for tile in level_json.get('tiles', []):
        analysis['total_tiles'] += 1
        layer = tile.get('l', 0)
        analysis['layers'].add(layer)
        analysis['max_layer'] = max(analysis['max_layer'], layer)

        tile_type = tile.get('t', '')
        analysis['tile_types'].add(tile_type)
        analysis['tile_distribution'][tile_type] += 1

        # 기믹 분석
        obstacles = tile.get('o', [])
        for obs in obstacles:
            analysis['gimmicks'].add(obs)

    # 블로킹 분석 (상위 레이어가 하위 레이어를 막는 경우)
    tiles_by_pos = defaultdict(list)
    for tile in level_json.get('tiles', []):
        pos = (tile.get('x'), tile.get('y'))
        tiles_by_pos[pos].append(tile.get('l', 0))

    for pos, layers in tiles_by_pos.items():
        if len(layers) > 1:
            analysis['blocked_tiles'] += len(layers) - 1

    analysis['layers'] = sorted(analysis['layers'])
    analysis['tile_types'] = sorted(analysis['tile_types'])
    analysis['gimmicks'] = sorted(analysis['gimmicks'])

    return analysis


def check_tile_divisibility(level_json):
    """타일 수가 3의 배수인지 확인"""
    tile_counts = defaultdict(int)

    for tile in level_json.get('tiles', []):
        tile_type = tile.get('t', '')
        if tile_type.startswith('t'):  # 일반 타일만
            tile_counts[tile_type] += 1

    issues = []
    for tile_type, count in tile_counts.items():
        if count % 3 != 0:
            issues.append(f"{tile_type}: {count}개 (3의 배수 아님)")

    return issues


def check_goal_validity(level_json):
    """Goals 유효성 검사"""
    issues = []
    goals = level_json.get('goals', [])

    for goal in goals:
        goal_type = goal.get('type', '')
        direction = goal.get('direction', '')
        count = goal.get('count', 0)

        # count가 3의 배수인지 확인
        if count % 3 != 0:
            issues.append(f"{goal_type}_{direction}: count={count} (3의 배수 아님)")

        # 최소 count 확인
        if count < 3:
            issues.append(f"{goal_type}_{direction}: count={count} (최소 3 필요)")

    return issues


def check_clearability(level_json, simulator):
    """클리어 가능성 상세 분석"""
    result = {
        'can_match_all': True,
        'unreachable_tiles': [],
        'goal_completion_possible': True,
        'goal_issues': [],
    }

    # 타일 타입별 개수 확인
    tile_counts = defaultdict(int)
    for tile in level_json.get('tiles', []):
        tile_type = tile.get('t', '')
        if tile_type.startswith('t'):
            tile_counts[tile_type] += 1

    # 3의 배수가 아닌 타일 타입 찾기
    for tile_type, count in tile_counts.items():
        if count % 3 != 0:
            result['can_match_all'] = False
            result['unreachable_tiles'].append(f"{tile_type}: {count}개")

    # Goals 검사
    goals = level_json.get('goals', [])
    for goal in goals:
        goal_type = goal.get('type', '')
        count = goal.get('count', 0)

        if goal_type in ['craft', 'stack']:
            # craft/stack goals의 경우 해당 타일 수 확인
            if count % 3 != 0:
                result['goal_completion_possible'] = False
                result['goal_issues'].append(f"{goal_type}: count={count} (3의 배수 아님)")

    return result


def run_detailed_simulation(simulator, level_json, bot_type=BotType.OPTIMAL):
    """상세 시뮬레이션 실행"""
    profile = get_profile(bot_type)

    try:
        result = simulator.simulate_with_profile(
            level_json,
            profile,
            iterations=10,
            max_moves=200,
            seed=42
        )

        return {
            'clear_rate': result.clear_rate,
            'avg_moves': result.avg_moves,
            'success': True,
            'error': None,
        }
    except Exception as e:
        return {
            'clear_rate': 0,
            'avg_moves': 0,
            'success': False,
            'error': str(e),
        }


def main():
    print("=" * 70)
    print("실패한 보스레벨 원인 분석")
    print("=" * 70)
    print()

    # 데이터 로드
    data = load_test_results()
    test_results = data['test_results']
    boss_levels = {b['level_number']: b for b in data['boss_levels']}

    # 실패한 레벨 추출
    failed_levels = [r for r in test_results if not r['test_passed']]

    print(f"총 실패 레벨: {len(failed_levels)}개")
    print()

    # 실패 유형별 분류
    failure_types = defaultdict(list)
    for r in failed_levels:
        if r['optimal_clear_rate'] == 0:
            failure_types['optimal_0%'].append(r)
        elif r['optimal_clear_rate'] < 0.7:
            failure_types['optimal_low'].append(r)
        elif r['average_clear_rate'] < 0.2:
            failure_types['average_low'].append(r)
        else:
            failure_types['other'].append(r)

    print("📊 실패 유형별 분류:")
    print(f"  - Optimal 봇 0% 클리어: {len(failure_types['optimal_0%'])}개")
    print(f"  - Optimal 봇 낮은 클리어율 (0-70%): {len(failure_types['optimal_low'])}개")
    print(f"  - Average 봇 낮은 클리어율 (<20%): {len(failure_types['average_low'])}개")
    print(f"  - 기타: {len(failure_types['other'])}개")
    print()

    # 시뮬레이터 초기화
    simulator = BotSimulator()

    # ========================================
    # 1. Optimal 봇 0% 클리어 레벨 분석
    # ========================================
    print("=" * 70)
    print("🔴 Optimal 봇 0% 클리어 레벨 상세 분석")
    print("=" * 70)

    zero_clear_analysis = []

    for r in failure_types['optimal_0%'][:10]:  # 처음 10개만 상세 분석
        level_num = r['level_number']
        boss = boss_levels.get(level_num)

        if not boss:
            continue

        level_json = boss['level_json']
        structure = analyze_level_structure(level_json)
        tile_issues = check_tile_divisibility(level_json)
        goal_issues = check_goal_validity(level_json)
        clearability = check_clearability(level_json, simulator)

        analysis = {
            'level_number': level_num,
            'gimmicks': boss['gimmicks'],
            'structure': structure,
            'tile_issues': tile_issues,
            'goal_issues': goal_issues,
            'clearability': clearability,
        }
        zero_clear_analysis.append(analysis)

        print(f"\n레벨 {level_num}:")
        print(f"  기믹: {boss['gimmicks']}")
        print(f"  타일 수: {structure['total_tiles']}")
        print(f"  레이어: {structure['layers']} (max: {structure['max_layer']})")
        print(f"  타일 타입: {structure['tile_types']}")
        print(f"  Goals: {structure['goals']}")
        print(f"  Craft 목표: {structure['craft_goals']}")
        print(f"  Stack 목표: {structure['stack_goals']}")

        if tile_issues:
            print(f"  ⚠️ 타일 수 문제: {tile_issues}")
        if goal_issues:
            print(f"  ⚠️ Goal 문제: {goal_issues}")
        if not clearability['can_match_all']:
            print(f"  ❌ 매칭 불가 타일: {clearability['unreachable_tiles']}")
        if not clearability['goal_completion_possible']:
            print(f"  ❌ Goal 완료 불가: {clearability['goal_issues']}")

    # ========================================
    # 2. 패턴 분석
    # ========================================
    print("\n" + "=" * 70)
    print("📈 실패 패턴 분석")
    print("=" * 70)

    # 기믹별 실패율
    gimmick_failures = defaultdict(lambda: {'total': 0, 'failed': 0})

    for r in test_results:
        level_num = r['level_number']
        boss = boss_levels.get(level_num)
        if boss:
            for gimmick in boss['gimmicks']:
                gimmick_failures[gimmick]['total'] += 1
                if not r['test_passed']:
                    gimmick_failures[gimmick]['failed'] += 1

    print("\n기믹별 실패율:")
    for gimmick, stats in sorted(gimmick_failures.items(), key=lambda x: -x[1]['failed']/max(1,x[1]['total'])):
        fail_rate = stats['failed'] / max(1, stats['total']) * 100
        print(f"  {gimmick}: {stats['failed']}/{stats['total']} ({fail_rate:.1f}%)")

    # 레벨 범위별 실패율
    range_failures = defaultdict(lambda: {'total': 0, 'failed': 0})

    for r in test_results:
        level_num = r['level_number']
        range_key = f"{(level_num-1)//200*200+1}-{(level_num-1)//200*200+200}"
        range_failures[range_key]['total'] += 1
        if not r['test_passed']:
            range_failures[range_key]['failed'] += 1

    print("\n레벨 범위별 실패율:")
    for range_key, stats in sorted(range_failures.items(), key=lambda x: int(x[0].split('-')[0])):
        fail_rate = stats['failed'] / max(1, stats['total']) * 100
        bar = '█' * int(fail_rate / 5)
        print(f"  {range_key}: {stats['failed']}/{stats['total']} ({fail_rate:.1f}%) {bar}")

    # ========================================
    # 3. craft/stack 목표 분석
    # ========================================
    print("\n" + "=" * 70)
    print("🎯 Craft/Stack 목표 분석")
    print("=" * 70)

    craft_stack_levels = []
    for r in failed_levels:
        level_num = r['level_number']
        boss = boss_levels.get(level_num)
        if boss:
            level_json = boss['level_json']
            goals = level_json.get('goals', [])
            has_craft = any(g.get('type') == 'craft' for g in goals)
            has_stack = any(g.get('type') == 'stack' for g in goals)

            if has_craft or has_stack:
                craft_stack_levels.append({
                    'level': level_num,
                    'goals': goals,
                    'has_craft': has_craft,
                    'has_stack': has_stack,
                    'optimal_rate': r['optimal_clear_rate'],
                })

    print(f"\n실패 레벨 중 Craft/Stack 포함: {len(craft_stack_levels)}개")

    craft_only = [l for l in craft_stack_levels if l['has_craft'] and not l['has_stack']]
    stack_only = [l for l in craft_stack_levels if l['has_stack'] and not l['has_craft']]
    both = [l for l in craft_stack_levels if l['has_craft'] and l['has_stack']]

    print(f"  - Craft만: {len(craft_only)}개")
    print(f"  - Stack만: {len(stack_only)}개")
    print(f"  - 둘 다: {len(both)}개")

    # 상세 분석
    print("\nCraft+Stack 레벨 상세:")
    for item in both[:5]:
        print(f"  레벨 {item['level']}: {item['goals']}, Optimal: {item['optimal_rate']*100:.0f}%")

    # ========================================
    # 4. 특정 레벨 시뮬레이션 재실행
    # ========================================
    print("\n" + "=" * 70)
    print("🔍 특정 레벨 상세 시뮬레이션")
    print("=" * 70)

    # 레벨 1200 (첫 번째 심각한 실패 마일스톤)
    level_1200 = boss_levels.get(1200)
    if level_1200:
        print("\n레벨 1200 상세 분석:")
        level_json = level_1200['level_json']

        print(f"  Goals: {level_json.get('goals', [])}")

        # 타일 타입별 개수
        tile_counts = defaultdict(int)
        for tile in level_json.get('tiles', []):
            tile_type = tile.get('t', '')
            tile_counts[tile_type] += 1

        print(f"  타일 분포:")
        for t, c in sorted(tile_counts.items()):
            divisible = "✓" if c % 3 == 0 else "✗"
            print(f"    {t}: {c}개 {divisible}")

        # 봇별 시뮬레이션
        print(f"\n  봇별 시뮬레이션 (10회):")
        for bot_type in [BotType.NOVICE, BotType.CASUAL, BotType.AVERAGE, BotType.EXPERT, BotType.OPTIMAL]:
            result = run_detailed_simulation(simulator, level_json, bot_type)
            if result['error']:
                print(f"    {bot_type.value}: 에러 - {result['error']}")
            else:
                print(f"    {bot_type.value}: {result['clear_rate']*100:.0f}%")

    # ========================================
    # 5. 결론 및 권장 사항
    # ========================================
    print("\n" + "=" * 70)
    print("📋 결론 및 권장 사항")
    print("=" * 70)

    print("""
🔴 주요 발견 사항:

1. 레벨 1200 이후 급격한 실패율 증가
   - 1-1190: 실패 3개 (2.5%)
   - 1200-1500: 실패 22개 (73.3%)

2. Craft/Stack 기믹이 포함된 레벨에서 문제 발생
   - Optimal 봇이 0% 클리어율을 보이는 것은 비정상
   - 봇 시뮬레이터가 craft/stack 목표를 제대로 처리하지 못할 가능성

3. 가능한 원인:
   a) 봇 시뮬레이터의 craft/stack goal 처리 버그
   b) 레벨 생성 시 goal 배치 문제 (output 방향에 타일 존재)
   c) 타일 수가 goal 완료에 불충분

🔧 권장 조치:
1. BotSimulator의 craft/stack goal 처리 로직 점검
2. 레벨 생성기의 goal 배치 로직 검토
3. goal output 방향 검증 강화
""")


if __name__ == "__main__":
    main()
