# TileMatch Level Designer - 변경 이력

## 2026-02-23

### 타일 종류 수 시스템 리팩토링 (v2)

#### 배경
- 다른 타일 매칭 게임 분석 결과, 난이도에 따라 타일 종류 수가 증감하는 패턴 확인
- 기존 시스템: 4-8종류 (고정적)
- 새 시스템: 10종류 기준선, 난이도별 8-12종류 가변

#### 변경 내용

| 레벨 구간 | 난이도 등급 | 변경 전 | 변경 후 |
|-----------|-------------|---------|---------|
| 1-10 | Tutorial | 4 | 4-5 (유지) |
| 11-30 | S (초반) | 4 | 5 |
| 31-60 | S (중반) | 5 | 7 |
| 61-225 | S (후반) | 5 | 8 |
| 226-600 | A | 6 | 9 |
| 601-1125 | B | 6 | **10** (기준선) |
| 1126-1500 | C/D | 7 | 11 |
| 1501+ | Master | 8 | 12 |

#### 수정 파일
1. **`backend/app/core/generator.py`**
   - `DEFAULT_TILE_TYPES`: 5종류 → 10종류
   - `get_gboost_style_layer_config()`: tile_types 값 업데이트
   - `get_tile_types_for_level()`: 그룹 순환 로직 제거, t1~t{n} 단순화

2. **`backend/app/models/leveling_config.py`**
   - `PHASE_CONFIGS`: min_tile_types, max_tile_types 값 업데이트
   - 모듈 docstring에 v2 변경사항 추가

3. **`SPECIFICATION.md`**
   - 섹션 5.1.2.1 추가: 난이도별 타일 종류 수 문서화

#### 설계 근거
- 보통 난이도(B등급)에서 10종류 타일 사용이 업계 표준
- 타일 종류 증가 → 덱(7슬롯) 막힘 확률 상승 → 난이도 증가
- 튜토리얼 레벨(1-10)은 학습 목적으로 4-5종류 유지

#### 관련 문서
- `claudedocs/TILE_TYPE_REFACTORING_DESIGN.md` - 상세 설계 문서

---

## 2024-12-18

### GBoost 연동 수정

#### 문제점
- 기존 GBoost 클라이언트가 잘못된 API 엔드포인트 사용
- townpop 프로젝트의 실제 API 패턴과 불일치
- 서버 응답의 `__keys/__vals` 압축 포맷 미지원

#### 해결
1. **백엔드 GBoost 클라이언트 재작성** (`backend/app/clients/gboost.py`)
   - `parse_gboost_response()` 함수 추가 - 압축 포맷 파싱
   - API 엔드포인트를 townpop 패턴으로 변경: `real_array.php?act=load&gid={AppID}&bid={board_id}&id={level_id}`
   - Save는 POST form data 방식으로 변경

2. **프론트엔드 설정 UI 추가** (`frontend/src/components/GBoostPanel/`)
   - Server URL, API Key, Project ID 입력 폼
   - 연결 테스트 기능
   - 설정 저장 API 연동

---

### UI 레이아웃 개선

#### 변경 전
- 에디터, 자동생성, 게임부스트 3개 탭 분리
- 레벨 불러오기/저장이 게임부스트 탭에만 존재
- 로컬 파일 불러오기 버튼 별도 존재

#### 변경 후
1. **에디터 탭 레이아웃 변경** (`frontend/src/App.tsx`)
   ```
   ┌────────────────────────────────────────────────────┐
   │ 그리드 에디터 (3/4)        │ 서버 레벨 (1/4)       │
   ├────────────────────────────┴───────────────────────┤
   │ 난이도 분석 (하단 전체)                             │
   └────────────────────────────────────────────────────┘
   ```

2. **LevelBrowser 컴포넌트 생성** (`frontend/src/components/GridEditor/LevelBrowser.tsx`)
   - 서버 레벨 목록 표시
   - 검색 및 정렬 기능 (번호, 날짜, 난이도)
   - 클릭 시 즉시 레벨 로드
   - 현재 레벨 저장 / 새 레벨로 저장 기능

3. **게임부스트 탭 → 설정 전용**
   - 서버 연결 설정만 담당
   - 사용 방법 가이드 추가

4. **로컬 파일 불러오기 제거**
   - GridEditor에서 "불러오기" 버튼 제거
   - 서버 레벨 목록에서만 로드 가능

---

### 서버 레벨 데이터 변환

#### 문제점
- 서버 레벨 JSON 구조가 프론트엔드 타입과 불일치
- 서버: `map` 객체 안에 layers 존재
- 프론트엔드: root 레벨에 layers 존재
- 레벨 로드 시 흰색 화면 발생

#### 해결
1. **데이터 변환 함수 추가** (`frontend/src/utils/helpers.ts`)
   - `convertServerLevelToFrontend()`: 서버 → 프론트엔드 형식 변환
   - `convertFrontendLevelToServer()`: 프론트엔드 → 서버 형식 변환
   - tiles 형식 변환: `[type, null]` → `[type, '']`

2. **LevelBrowser에서 변환 적용**
   - 레벨 로드 시 `convertServerLevelToFrontend()` 호출

---

### 다양한 레벨 크기 지원

#### 문제점
- 레벨마다 layer 수, 그리드 크기가 다름
- 레벨 1: 8 layers, 7x7/8x8
- 레벨 2: 4 layers, 11x11/12x12
- selectedLayer가 새 레벨의 layer 수를 초과하면 흰색 화면

#### 해결
1. **levelStore.ts - setLevel 수정**
   - 새 레벨 로드 시 selectedLayer 자동 조정
   - maxLayer를 초과하면 maxLayer로 변경

2. **TileGrid.tsx - 안전 처리**
   - cols/rows 파싱 시 기본값 설정: `parseInt(layerData.col) || 8`
   - tiles 없을 때 빈 객체 사용
   - 레이어 데이터 없을 때 친절한 안내 메시지

3. **LayerSelector.tsx - 안전 처리**
   - tiles 접근 시 옵셔널 체이닝 사용

---

## 수정된 파일 목록

### Backend
- `backend/app/clients/gboost.py` - GBoost 클라이언트 전체 재작성
- `backend/app/api/routes/gboost.py` - Config API 추가

### Frontend
- `frontend/src/App.tsx` - 레이아웃 변경
- `frontend/src/components/GridEditor/index.tsx` - 로컬 불러오기 제거
- `frontend/src/components/GridEditor/LevelBrowser.tsx` - 신규 생성
- `frontend/src/components/GridEditor/TileGrid.tsx` - 안전 처리 추가
- `frontend/src/components/GridEditor/LayerSelector.tsx` - 안전 처리 추가
- `frontend/src/components/GBoostPanel/index.tsx` - 설정 전용으로 변경
- `frontend/src/components/GBoostPanel/LevelSelector.tsx` - UI 개선
- `frontend/src/stores/levelStore.ts` - setLevel 수정
- `frontend/src/stores/uiStore.ts` - GBoost 설정 상태 추가
- `frontend/src/api/gboost.ts` - Config API 함수 추가
- `frontend/src/utils/helpers.ts` - 데이터 변환 함수 추가
