# TileMatchAutoLevel - Claude Code Guidelines

## Project Overview
타일 매칭 퍼즐 게임의 레벨 자동 생성 및 난이도 분석 도구

## Testing Guidelines

### Playwright 활용 (적극 권장)
UI 관련 테스트나 기능 검증 시 Playwright MCP를 적극 활용하세요:

1. **레벨 생성 테스트**
   - 레벨 세트 생성 시 UI에서 진행 상황 확인
   - 생성된 레벨의 검증 결과 확인

2. **난이도 검증 테스트**
   - AutoPlay 패널에서 봇별 클리어율 확인
   - 목표 클리어율과 실제 클리어율 비교

3. **일반적인 테스트 흐름**
   ```
   1. browser_navigate → http://localhost:5173
   2. browser_snapshot → 현재 상태 확인
   3. browser_click → UI 조작
   4. browser_wait_for → 결과 대기
   5. browser_snapshot → 결과 확인
   ```

### API 테스트
백엔드 API 테스트 시:
- `/api/generate/validated` - 검증 기반 레벨 생성
- `/api/analyze/autoplay` - 봇 시뮬레이션 기반 난이도 분석

## Key Endpoints

### Level Generation
- `POST /api/generate` - 기본 레벨 생성
- `POST /api/generate/validated` - 검증 기반 레벨 생성 (재시도 포함)

### Analysis
- `POST /api/analyze` - 정적 난이도 분석
- `POST /api/analyze/autoplay` - 봇 시뮬레이션 분석

## Development Notes

### 동적 목표 클리어율
- 정적 분석 점수 기반으로 봇별 목표 클리어율 동적 계산
- 쉬운 레벨(S/A등급): 높은 목표 클리어율
- 어려운 레벨(C/D등급): 낮은 목표 클리어율

### 레벨 생성 재시도 로직
- 프론트엔드: validation_passed가 false면 최대 10회 재시도
- 백엔드: max_retries 파라미터로 내부 재시도 횟수 설정
