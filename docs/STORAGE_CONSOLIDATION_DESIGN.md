# 레벨 저장소 통합 설계

## 현재 상태

### 저장소 구조
| 저장소 | 위치 | 레벨 수 | 용도 |
|--------|------|---------|------|
| 백엔드 파일 시스템 | `backend/app/storage/local_levels/` | ~2,051개 | 주 저장소 |
| 브라우저 localStorage | `tilematch_local_levels` 키 | 브라우저별 상이 | 배포 환경 보조 |

### 현재 동작 방식
```
목록 조회: 백엔드 API + localStorage 병합 (중복 ID 제거)
레벨 로드: 백엔드 먼저 시도 → 실패시 localStorage
레벨 저장: localStorage에만 저장
레벨 삭제: 백엔드 먼저 시도 → localStorage도 삭제
```

### 문제점
1. 저장이 localStorage에만 되어 백엔드와 동기화 안됨
2. 브라우저 변경/초기화 시 localStorage 데이터 손실
3. 두 저장소 간 데이터 불일치 가능

---

## 목표 설계

### 원칙
- **백엔드 = 주 저장소** (Single Source of Truth)
- **localStorage = 오프라인 캐시/폴백**
- 백엔드 가용 시 항상 백엔드 우선

### 새로운 동작 방식
```
목록 조회: 백엔드 API (localStorage는 오프라인시만)
레벨 로드: 백엔드 우선 → 실패시 localStorage 캐시
레벨 저장: 백엔드 우선 → 실패시 localStorage (pending 상태)
레벨 삭제: 백엔드 + localStorage 동시 삭제
동기화:    localStorage pending → 백엔드 일괄 업로드
```

---

## 구현 상세

### 1. 저장 로직 변경 (`localLevelsApi.ts`)

```typescript
// 현재
export async function saveLocalLevel(levelData: LocalLevel): Promise<SaveLevelResponse> {
  const result = saveLocalLevelToStorage({...}); // localStorage만
  return result;
}

// 변경 후
export async function saveLocalLevel(levelData: LocalLevel): Promise<SaveLevelResponse> {
  try {
    // 1. 백엔드 저장 시도
    const response = await apiClient.post('/simulate/local/save', {
      level_id: levelData.level_id,
      level_data: levelData.level_data,
      metadata: levelData.metadata,
    });

    // 2. 성공시 localStorage 캐시도 업데이트
    saveLocalLevelToStorage({...levelData, source: 'backend'});

    return { success: true, level_id: response.data.level_id, message: response.data.message };
  } catch (err) {
    // 3. 백엔드 실패시 localStorage에 pending 상태로 저장
    const result = saveLocalLevelToStorage({
      ...levelData,
      source: 'localStorage_pending', // 동기화 필요 표시
    });
    return { ...result, message: `오프라인 저장됨 (동기화 필요): ${result.message}` };
  }
}
```

### 2. 동기화 함수 추가

```typescript
/**
 * localStorage의 pending 레벨들을 백엔드로 동기화
 */
export async function syncPendingLevelsToBackend(): Promise<SyncResult> {
  const localLevels = getAllLocalLevels();
  const pendingLevels = localLevels.filter(l => l.source === 'localStorage_pending');

  const results = { synced: 0, failed: 0, errors: [] };

  for (const level of pendingLevels) {
    try {
      await apiClient.post('/simulate/local/save', {
        level_id: level.id,
        level_data: level.level_data,
        metadata: { ...level, source: 'synced_from_local' },
      });

      // 성공시 source 업데이트
      updateLocalLevelSource(level.id, 'backend');
      results.synced++;
    } catch (err) {
      results.failed++;
      results.errors.push({ id: level.id, error: err.message });
    }
  }

  return results;
}

/**
 * localStorage 전체를 백엔드로 마이그레이션 (1회성)
 */
export async function migrateAllLocalStorageToBackend(): Promise<MigrateResult> {
  const localLevels = getAllLocalLevels();
  const localOnlyLevels = localLevels.filter(l =>
    l.source !== 'backend' && l.source !== 'synced_from_local'
  );

  // 백엔드에 이미 있는 ID 확인
  const backendList = await apiClient.get('/simulate/local/list');
  const backendIds = new Set(backendList.data.levels.map(l => l.id));

  const toMigrate = localOnlyLevels.filter(l => !backendIds.has(l.id));

  // 일괄 업로드...
}
```

### 3. 목록 조회 로직 단순화

```typescript
// 현재: 백엔드 + localStorage 병합
// 변경 후: 백엔드 우선, 오프라인시만 localStorage

export async function listLocalLevels(): Promise<LocalLevelListResponse> {
  try {
    // 백엔드 API 호출
    const response = await apiClient.get('/simulate/local/list');

    // pending 레벨 수 표시 (동기화 필요 알림용)
    const pendingCount = getAllLocalLevels()
      .filter(l => l.source === 'localStorage_pending').length;

    return {
      levels: response.data.levels,
      count: response.data.count,
      storage_path: response.data.storage_path,
      pending_sync_count: pendingCount, // 새 필드
    };
  } catch (err) {
    // 오프라인: localStorage만 사용
    console.warn('Backend unavailable, using localStorage cache');
    return getLocalStorageLevels();
  }
}
```

### 4. UI 변경 사항

#### 동기화 알림 표시
```
┌─────────────────────────────────────┐
│ 로컬 레벨 (2,051개)                 │
│ ⚠️ 3개 레벨 동기화 대기 중 [동기화] │
└─────────────────────────────────────┘
```

#### 저장 상태 표시
- 백엔드 저장 성공: ✅ 저장 완료
- localStorage 저장 (오프라인): ⚠️ 오프라인 저장 (동기화 필요)

---

## 데이터 구조 변경

### StoredLocalLevel 타입 확장

```typescript
export interface StoredLocalLevel {
  id: string;
  name: string;
  // ... 기존 필드들

  // source 값 확장
  source: 'backend' | 'localStorage_pending' | 'synced_from_local' | 'local';

  // 동기화 메타데이터 (선택)
  sync_status?: {
    last_synced_at?: string;
    sync_error?: string;
  };
}
```

---

## 마이그레이션 계획

### Phase 1: 저장 로직 변경
1. `saveLocalLevel` → 백엔드 우선 저장
2. `source` 필드로 저장 위치 추적

### Phase 2: 동기화 기능 추가
1. `syncPendingLevelsToBackend()` 구현
2. UI에 동기화 버튼/알림 추가

### Phase 3: localStorage 역할 축소
1. 목록 조회에서 localStorage 제외 (캐시 용도만)
2. 오프라인 감지 후 자동 동기화

### Phase 4: (선택) localStorage 정리
1. 마이그레이션 완료 후 localStorage 데이터 정리 옵션

---

## 파일 변경 목록

| 파일 | 변경 내용 |
|------|----------|
| `frontend/src/services/localLevelsApi.ts` | 저장/목록 로직 변경, 동기화 함수 추가 |
| `frontend/src/storage/levelStorage.ts` | source 타입 확장, 동기화 헬퍼 추가 |
| `frontend/src/components/LocalLevelsList.tsx` (또는 해당 UI) | 동기화 버튼, pending 알림 |
| `frontend/src/types/index.ts` | 타입 정의 확장 |

---

## 데이터 손실 방지

### 위험 요소
| 시나리오 | 위험도 | 대응 |
|----------|--------|------|
| localStorage에만 있는 레벨 | ⚠️ 중간 | 마이그레이션 전 반드시 백업 |
| 브라우저별 localStorage 차이 | ⚠️ 중간 | 각 브라우저에서 개별 마이그레이션 |
| 마이그레이션 전 삭제 | 🔴 높음 | 삭제 기능은 마이그레이션 완료 후에만 활성화 |

### 안전한 마이그레이션 순서
```
1. [필수] localStorage 레벨 export (JSON 백업 파일 생성)
2. [필수] 백엔드 가용성 확인
3. localStorage → 백엔드 마이그레이션 실행
4. 마이그레이션 결과 확인 (성공/실패 개수)
5. [선택] 성공 확인 후 localStorage 정리
```

### 구현 시 체크리스트
- [ ] `exportAllData()` 함수로 백업 기능 제공 (이미 존재)
- [ ] 마이그레이션 전 confirm 다이얼로그 표시
- [ ] 마이그레이션 실패한 레벨 목록 표시
- [ ] localStorage 삭제는 별도 버튼으로 분리 (자동 삭제 금지)

---

## 예상 질문

**Q: 백엔드가 없는 배포 환경은?**
A: localStorage가 폴백으로 동작. 백엔드 복구 시 자동/수동 동기화.

**Q: 동일 ID 충돌 시?**
A: 백엔드 데이터 우선. localStorage는 백엔드 복사본으로 덮어씀.

**Q: localStorage 용량 제한?**
A: 약 5MB. 백엔드 주 저장소이므로 localStorage는 최근 N개만 캐시 가능.

---

## 빠른 시작 (다음 세션용)

### 1. 현재 상태 파악
```bash
# 백엔드 레벨 수 확인
ls backend/app/storage/local_levels/ | wc -l

# 브라우저 localStorage 확인 (개발자 도구 Console)
JSON.parse(localStorage.getItem('tilematch_local_levels'))?.length || 0
```

### 2. 관련 파일
- `frontend/src/services/localLevelsApi.ts` - 주 수정 대상
- `frontend/src/storage/levelStorage.ts` - localStorage 헬퍼
- `backend/app/api/routes/simulate.py:1314` - 백엔드 저장 API

### 3. 테스트 시나리오
1. 레벨 저장 → 백엔드 파일 생성 확인
2. 백엔드 끄고 저장 → localStorage pending 저장 확인
3. 백엔드 켜고 동기화 → pending 레벨 백엔드 이동 확인
