# 세션 시작 - 프로젝트 컨텍스트 로드

세션을 시작하고 작업에 필요한 문서를 자동으로 로드합니다.

---

## 1. TODO.md 상태 확인

`claudedocs/TODO.md`를 읽고 다음을 확인:
- 진행 중 작업이 있는지 확인
- 대기 중 작업 목록 확인
- 현재 작업의 **작업 유형 키워드** 파악

---

## 2. 작업 유형별 자동 문서 로드

TODO.md의 작업 설명에서 키워드를 감지하여 관련 문서를 **자동으로 읽기**:

| 키워드 | 로드할 문서 | 참조 섹션 |
|--------|------------|----------|
| 시뮬레이션, 봇, Bot, Simulator | [PROJECT_INDEX.md](../../claudedocs/PROJECT_INDEX.md) | 봇 프로필, 기믹 목록 |
| 레벨, Level, 생성, Generate | [LEVEL_GENERATION_GUIDE.md](../../claudedocs/LEVEL_GENERATION_GUIDE.md) | 레벨 생성 가이드 |
| 벤치마크, Benchmark, 티어 | [BENCHMARK_API_GUIDE.md](../../claudedocs/BENCHMARK_API_GUIDE.md) | 벤치마크 API |
| 자동화, Automation, CLI | [AUTOMATION_SUMMARY.md](../../claudedocs/AUTOMATION_SUMMARY.md) | 자동화 도구 |
| 로컬, Local, 저장 | [LOCAL_LEVELS_GUIDE.md](../../claudedocs/LOCAL_LEVELS_GUIDE.md) | 로컬 레벨 관리 |
| 기믹, Gimmick, Ice, Bomb, Grass | [PROJECT_INDEX.md](../../claudedocs/PROJECT_INDEX.md) | 구현된 기믹 섹션 |
| API, 엔드포인트, Endpoint | [BENCHMARK_API_GUIDE.md](../../claudedocs/BENCHMARK_API_GUIDE.md) | API 엔드포인트 |
| 프론트엔드, Frontend, UI | [PROJECT_INDEX.md](../../claudedocs/PROJECT_INDEX.md) | 프로젝트 구조 |
| 백엔드, Backend, Python | [PROJECT_INDEX.md](../../claudedocs/PROJECT_INDEX.md) | 프로젝트 구조 |

### 자동 로드 로직

```
작업 설명 분석 → 키워드 매칭 → 해당 문서 Read → 가이드 섹션 요약 제시
```

**복합 작업 시**: 여러 키워드 감지되면 관련 문서 **모두** 로드

---

## 3. 프로젝트 핵심 정보 확인

PROJECT_INDEX.md에서 필수 정보 리마인드:
- 구현된 기믹 목록 (15개)
- 봇 프로필 (5종)
- 주요 API 엔드포인트
- 프로젝트 구조

---

## 4. 세션 상태 보고

```
📋 세션 시작 보고

🔄 진행중 작업: [작업명]
   - 작업 유형: [백엔드/프론트엔드/기믹/...]
   - 참조 문서: [로드된 문서 목록]

📚 로드된 가이드 요약:
   - [핵심 체크리스트 또는 단계 요약]

⬜ 대기중 작업: [N개]

💡 작업 중 문서 재참조 필요시 직접 요청
```

---

## 5. 사용자 확인

- 진행 중 작업 있으면: "이전 작업을 이어서 진행할까요?"
- 대기 중 작업만 있으면: "다음 우선순위 작업을 시작할까요?"
- 새 요청이면: 기존 작업과의 관련성/충돌 여부 판단 후 진행
