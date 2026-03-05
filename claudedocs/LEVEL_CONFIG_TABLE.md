# 레벨 설정 통합 테이블 (LEVEL_CONFIG_TABLE)

## 개요
모든 레벨 생성 파라미터를 한 곳에서 관리하는 통합 설정 테이블.
위치: `backend/app/core/generator.py`

## 설정 테이블

| 레벨 범위 | 층수 (min-max) | 그리드 | 타일 범위 | 타일 종류 | 설명 |
|-----------|---------------|--------|-----------|----------|------|
| 1-3 | 1-2 | 4x4 | 9-18 | 4 | 튜토리얼 |
| 4-5 | 3-4 | 4x4 | 18-36 | 5 | 후반 튜토리얼 |
| 6-10 | 3-4 | 5x5 | 18-36 | 5 | 후반 튜토리얼 |
| 11-30 | 3-4 | 6x6 | 24-48 | 6 | 초반 |
| 31-60 | 3-4 | 7x7 | 30-50 | 8 | 초중반 |
| 61-100 | 4-5 | 8x8 | 50-80 | 9 | 중반 |
| 101-225 | 4-5 | 8x8 | 60-90 | 9 | 중후반 |
| 226-600 | 4-5 | 8x8 | 70-100 | 10 | A등급 주력 |
| 601-1125 | 5-5 | 8x8 | 75-105 | 11 | B등급 기준선 |
| 1126-1500 | 5-6 | 8x8 | 84-120 | 12 | C/D등급 |
| 1501+ | 5-6 | 8x8 | 96-120 | 13 | 엔드게임 |

## 그리드 크기 참고
- **홀수 레이어**: 그리드 크기 그대로 (예: 4x4)
- **짝수 레이어**: 그리드 크기 + 1 (예: 5x5)

## 관련 함수

### `get_gboost_style_layer_config(level_number: int)`
레벨 번호에 따른 전체 설정 반환
```python
{
    "min_layers": int,
    "max_layers": int,
    "cols": int,
    "rows": int,
    "total_tile_range": (int, int),
    "tile_types": int,
    "description": str
}
```

### `get_grid_size_for_level(level_number: int)`
레벨 번호에 따른 그리드 크기 반환 (정사각형)
```python
(cols, rows)  # 예: (4, 4), (5, 5), etc.
```

## 설정 변경 방법
1. `backend/app/core/generator.py` 파일 열기
2. `LEVEL_CONFIG_TABLE` 찾기
3. 튜플 형식으로 설정 수정:
   ```python
   (max_level, min_layers, max_layers, grid_size, tile_range, tile_types, description)
   ```

## 변경 이력
- **v3** (2025-03):
  - 타일 종류 수 전체 +1 (1-3레벨 제외)
  - 그리드 크기 레벨별 동적 결정
  - 층수 조정 (4-30레벨: 3-4층)
  - 통합 테이블로 리팩토링
