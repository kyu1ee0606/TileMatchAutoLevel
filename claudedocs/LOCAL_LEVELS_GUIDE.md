# 로컬 레벨 관리 가이드

**날짜**: 2025-12-22
**목적**: 생성된 레벨을 로컬에서 저장, 로드, 테스트하는 방법

---

## 개요

자동 생성된 레벨을 게임 서버와 별개로 로컬에서 관리할 수 있는 시스템입니다.

### 주요 기능

1. **로컬 저장소**: 생성된 레벨을 로컬 파일 시스템에 저장
2. **API 관리**: REST API를 통한 레벨 CRUD 작업
3. **웹 UI 통합**: 프론트엔드에서 직접 접근 및 테스트
4. **일괄 임포트**: 생성 도구 출력을 직접 임포트
5. **서버 업로드 준비**: 향후 게임 서버 업로드 기능 확장 가능

---

## 로컬 저장소 구조

### 저장 위치

```
backend/app/storage/local_levels/
├── .gitkeep
├── custom_level_01.json
├── medium_01.json
├── hard_test_01.json
└── ...
```

### 레벨 파일 형식

각 레벨은 JSON 파일로 저장됩니다:

```json
{
  "level_id": "custom_level_01",
  "level_data": {
    "layer": 2,
    "randSeed": 42,
    "useTileCount": 5,
    "goals": {
      "t1": 9,
      "t2": 9,
      "t3": 9,
      "t4": 9,
      "t5": 9
    },
    "max_moves": 50,
    "layer_0": {
      "tiles": {...},
      "col": 9
    },
    "layer_1": {
      "tiles": {...},
      "col": 9
    }
  },
  "metadata": {
    "name": "Custom Level 01",
    "description": "My first custom level",
    "tags": ["custom", "2_layer"],
    "difficulty": "medium",
    "created_at": "2025-12-22T10:30:00",
    "saved_at": "2025-12-22T10:30:00",
    "source": "local",
    "validation_status": "pass",
    "actual_clear_rates": {
      "novice": 0.30,
      "casual": 0.55,
      "average": 0.75,
      "expert": 0.90,
      "optimal": 0.98
    },
    "suggestions": [],
    "generation_config": {...}
  }
}
```

---

## API 엔드포인트

### 1. 로컬 레벨 목록 조회

**Endpoint**: `GET /api/simulate/local/list`

모든 로컬 저장 레벨의 목록을 반환합니다.

**Response**:
```json
{
  "levels": [
    {
      "id": "custom_level_01",
      "name": "Custom Level 01",
      "description": "My first custom level",
      "tags": ["custom", "2_layer"],
      "difficulty": "medium",
      "created_at": "2025-12-22T10:30:00",
      "source": "local",
      "validation_status": "pass"
    }
  ],
  "count": 1,
  "storage_path": "/Users/casualdev/TileMatchAutoLevel/backend/app/storage/local_levels"
}
```

### 2. 특정 로컬 레벨 조회

**Endpoint**: `GET /api/simulate/local/{level_id}`

특정 로컬 레벨의 전체 데이터를 반환합니다.

**Example**:
```bash
curl http://localhost:8000/api/simulate/local/custom_level_01
```

**Response**:
```json
{
  "level_id": "custom_level_01",
  "level_data": {...},
  "metadata": {...}
}
```

### 3. 로컬 레벨 저장

**Endpoint**: `POST /api/simulate/local/save`

새로운 레벨을 로컬에 저장하거나 기존 레벨을 업데이트합니다.

**Request Body**:
```json
{
  "level_id": "custom_level_01",
  "level_data": {
    "layer": 1,
    "randSeed": 0,
    "useTileCount": 3,
    "goals": {"t1": 3, "t2": 3, "t3": 3},
    "max_moves": 50,
    "layer_0": {
      "tiles": {
        "1_1": ["t1"],
        "1_2": ["t1"],
        "1_3": ["t1"],
        "2_1": ["t2"],
        "2_2": ["t2"],
        "2_3": ["t2"],
        "3_1": ["t3"],
        "3_2": ["t3"],
        "3_3": ["t3"]
      },
      "col": 5
    }
  },
  "metadata": {
    "name": "My Custom Level",
    "description": "A simple test level",
    "tags": ["custom", "test"],
    "difficulty": "easy"
  }
}
```

**Response**:
```json
{
  "success": true,
  "level_id": "custom_level_01",
  "file_path": "/path/to/custom_level_01.json",
  "message": "Level custom_level_01 saved successfully"
}
```

### 4. 로컬 레벨 삭제

**Endpoint**: `DELETE /api/simulate/local/{level_id}`

로컬 저장소에서 레벨을 삭제합니다.

**Example**:
```bash
curl -X DELETE http://localhost:8000/api/simulate/local/custom_level_01
```

**Response**:
```json
{
  "success": true,
  "level_id": "custom_level_01",
  "message": "Level custom_level_01 deleted successfully"
}
```

### 5. 생성된 레벨 일괄 임포트

**Endpoint**: `POST /api/simulate/local/import-generated`

`generate_benchmark_levels.py`의 출력 파일을 직접 임포트합니다.

**Request Body**:
```json
{
  "generator_version": "1.0",
  "generation_date": "2025-12-22",
  "seed": 42,
  "levels": [
    {
      "config": {...},
      "level_json": {...},
      "actual_clear_rates": {...},
      "validation_status": "pass",
      "suggestions": []
    }
  ]
}
```

**Response**:
```json
{
  "success": true,
  "imported_count": 10,
  "error_count": 0,
  "imported_levels": [
    "medium_01",
    "medium_02",
    ...
  ],
  "errors": null
}
```

### 6. 서버 업로드 (향후 기능)

**Endpoint**: `POST /api/simulate/local/upload-to-server`

로컬 레벨을 게임 부스트 서버에 업로드합니다.

**Request Body**:
```json
{
  "level_id": "custom_level_01",
  "server_config": {
    "api_endpoint": "https://game-server.com/api/levels",
    "auth_token": "your-auth-token"
  }
}
```

**현재 상태**: 구현 예정 (placeholder)

---

## 사용 시나리오

### 시나리오 1: 레벨 생성 → 저장 → 테스트

```bash
# Step 1: 레벨 생성
python3 generate_benchmark_levels.py --tier medium --count 5 --validate --output new_levels.json

# Step 2: 생성된 레벨 임포트
curl -X POST http://localhost:8000/api/simulate/local/import-generated \
  -H "Content-Type: application/json" \
  -d @new_levels.json

# Step 3: 로컬 레벨 목록 확인
curl http://localhost:8000/api/simulate/local/list

# Step 4: 특정 레벨 테스트 (웹 UI 또는 API)
curl http://localhost:8000/api/simulate/local/medium_01
```

### 시나리오 2: 프론트엔드에서 직접 관리

```typescript
// 1. 로컬 레벨 목록 로드
async function loadLocalLevels() {
  const response = await fetch('/api/simulate/local/list');
  const data = await response.json();
  return data.levels;
}

// 2. 특정 레벨 로드
async function loadLevel(levelId: string) {
  const response = await fetch(`/api/simulate/local/${levelId}`);
  const data = await response.json();
  return data;
}

// 3. 레벨 플레이
async function playLevel(levelId: string) {
  // 레벨 데이터 로드
  const level = await loadLevel(levelId);

  // 시뮬레이션 또는 실제 플레이
  const simulation = await fetch('/api/simulate/visual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_json: level.level_data,
      bot_types: ['optimal'],
      max_moves: level.level_data.max_moves,
      seed: 42
    })
  });

  return simulation.json();
}

// 4. 커스텀 레벨 저장
async function saveCustomLevel(levelData: any) {
  const response = await fetch('/api/simulate/local/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_id: 'custom_' + Date.now(),
      level_data: levelData,
      metadata: {
        name: 'My Custom Level',
        description: 'Created in web editor',
        tags: ['custom'],
        difficulty: 'medium',
        source: 'web_editor'
      }
    })
  });

  return response.json();
}

// 5. 레벨 삭제
async function deleteLevel(levelId: string) {
  const response = await fetch(`/api/simulate/local/${levelId}`, {
    method: 'DELETE'
  });
  return response.json();
}
```

### 시나리오 3: 웹 UI 레벨 관리 화면

```typescript
// LocalLevelManager.tsx
import React, { useEffect, useState } from 'react';

interface LocalLevel {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  created_at: string;
  validation_status: string;
}

export function LocalLevelManager() {
  const [levels, setLevels] = useState<LocalLevel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLevels();
  }, []);

  async function loadLevels() {
    try {
      const response = await fetch('/api/simulate/local/list');
      const data = await response.json();
      setLevels(data.levels);
    } catch (error) {
      console.error('Failed to load levels:', error);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(levelId: string) {
    if (!confirm(`Delete level ${levelId}?`)) return;

    try {
      await fetch(`/api/simulate/local/${levelId}`, { method: 'DELETE' });
      await loadLevels(); // Refresh list
    } catch (error) {
      console.error('Failed to delete level:', error);
    }
  }

  async function handlePlay(levelId: string) {
    // Navigate to level player
    window.location.href = `/play?level=${levelId}&source=local`;
  }

  if (loading) return <div>Loading...</div>;

  return (
    <div className="local-level-manager">
      <h2>Local Levels ({levels.length})</h2>

      <div className="level-grid">
        {levels.map(level => (
          <div key={level.id} className="level-card">
            <h3>{level.name}</h3>
            <p>{level.description}</p>

            <div className="level-meta">
              <span className="difficulty">{level.difficulty}</span>
              <span className="validation">{level.validation_status}</span>
              {level.tags.map(tag => (
                <span key={tag} className="tag">{tag}</span>
              ))}
            </div>

            <div className="level-actions">
              <button onClick={() => handlePlay(level.id)}>
                Play
              </button>
              <button onClick={() => handleDelete(level.id)}>
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="level-actions-toolbar">
        <button onClick={() => {/* Import dialog */}}>
          Import Generated Levels
        </button>
        <button onClick={() => {/* Create new dialog */}}>
          Create New Level
        </button>
      </div>
    </div>
  );
}
```

### 시나리오 4: 생성된 레벨 자동 임포트

```typescript
// LevelImporter.tsx
async function importGeneratedLevels(file: File) {
  try:
    // Read file content
    const content = await file.text();
    const data = JSON.parse(content);

    // Import to local storage
    const response = await fetch('/api/simulate/local/import-generated', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    const result = await response.json();

    console.log(`Imported ${result.imported_count} levels`);
    if (result.error_count > 0) {
      console.error(`Failed to import ${result.error_count} levels:`, result.errors);
    }

    return result;
  } catch (error) {
    console.error('Import failed:', error);
    throw error;
  }
}

// Usage in component
function ImportDialog() {
  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const result = await importGeneratedLevels(file);
      alert(`Successfully imported ${result.imported_count} levels!`);
      // Refresh level list
      window.location.reload();
    } catch (error) {
      alert('Import failed: ' + error);
    }
  };

  return (
    <div className="import-dialog">
      <h3>Import Generated Levels</h3>
      <p>Select a file from generate_benchmark_levels.py output</p>
      <input
        type="file"
        accept=".json"
        onChange={handleFileSelect}
      />
    </div>
  );
}
```

---

## 로컬 레벨과 벤치마크 레벨 비교

| 특성 | 로컬 레벨 | 벤치마크 레벨 |
|------|-----------|---------------|
| 저장 위치 | 로컬 파일 시스템 | 코드베이스 (Python 파일) |
| 접근 방법 | `/api/simulate/local/*` | `/api/simulate/benchmark/*` |
| 용도 | 테스트, 실험, 커스텀 레벨 | 공식 난이도 검증용 |
| 수정 가능 | 자유롭게 추가/삭제 | 코드 수정 필요 |
| 서버 업로드 | 향후 지원 예정 | 직접 배포 |
| 검증 상태 | 메타데이터에 저장 | 별도 검증 필요 |

---

## 서버 업로드 기능 (향후 확장)

### 현재 상태

`POST /api/simulate/local/upload-to-server` 엔드포인트는 placeholder로 구현되어 있습니다.

### 구현 계획

1. **게임 서버 API 연동**
   - 엔드포인트 설정
   - 인증/권한 관리
   - 레벨 형식 변환 (필요시)

2. **업로드 워크플로우**
   ```
   로컬 레벨 생성 → 검증 → 로컬 저장 → 사용자 승인 → 서버 업로드
   ```

3. **서버 응답 처리**
   - 성공: 서버 레벨 ID 저장
   - 실패: 에러 메시지 표시 및 재시도

4. **양방향 동기화**
   - 서버 레벨 → 로컬 다운로드
   - 로컬 레벨 → 서버 업로드
   - 충돌 해결 전략

### 구현 예시 (미래)

```python
@router.post("/local/upload-to-server")
async def upload_to_server(level_id: str, server_config: Dict[str, Any]):
    """Upload local level to game server."""
    # 1. Load local level
    local_level = await get_local_level(level_id)

    # 2. Convert format if needed
    server_format = convert_to_server_format(local_level)

    # 3. Authenticate
    auth_token = server_config.get("auth_token")
    headers = {"Authorization": f"Bearer {auth_token}"}

    # 4. Upload
    async with httpx.AsyncClient() as client:
        response = await client.post(
            server_config["api_endpoint"],
            json=server_format,
            headers=headers
        )

    # 5. Update local metadata
    if response.status_code == 200:
        server_level_id = response.json()["level_id"]
        await update_local_metadata(level_id, {
            "server_id": server_level_id,
            "uploaded_at": datetime.now().isoformat(),
            "server_status": "published"
        })

    return {"success": True, "server_level_id": server_level_id}
```

---

## 테스트 방법

### API 테스트 스크립트

```bash
#!/bin/bash
# test_local_levels_api.sh

echo "========================================="
echo "Testing Local Levels API"
echo "========================================="
echo ""

# Test 1: List local levels
echo "Test 1: GET /api/simulate/local/list"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/list | python3 -m json.tool
echo ""

# Test 2: Save a custom level
echo "Test 2: POST /api/simulate/local/save"
echo "-----------------------------------------"
curl -s -X POST http://localhost:8000/api/simulate/local/save \
  -H "Content-Type: application/json" \
  -d '{
    "level_id": "test_level_01",
    "level_data": {
      "layer": 1,
      "randSeed": 0,
      "useTileCount": 3,
      "goals": {"t1": 3, "t2": 3, "t3": 3},
      "max_moves": 50,
      "layer_0": {
        "tiles": {
          "1_1": ["t1"], "1_2": ["t1"], "1_3": ["t1"],
          "2_1": ["t2"], "2_2": ["t2"], "2_3": ["t2"],
          "3_1": ["t3"], "3_2": ["t3"], "3_3": ["t3"]
        },
        "col": 5
      }
    },
    "metadata": {
      "name": "Test Level",
      "description": "API test level",
      "tags": ["test"],
      "difficulty": "easy"
    }
  }' | python3 -m json.tool
echo ""

# Test 3: Get specific level
echo "Test 3: GET /api/simulate/local/test_level_01"
echo "-----------------------------------------"
curl -s http://localhost:8000/api/simulate/local/test_level_01 | python3 -m json.tool
echo ""

# Test 4: Delete level
echo "Test 4: DELETE /api/simulate/local/test_level_01"
echo "-----------------------------------------"
curl -s -X DELETE http://localhost:8000/api/simulate/local/test_level_01 | python3 -m json.tool
echo ""

echo "========================================="
echo "All tests completed!"
echo "========================================="
```

### 사용:
```bash
chmod +x test_local_levels_api.sh
./test_local_levels_api.sh
```

---

## 관련 파일

- **API 라우터**: [backend/app/api/routes/simulate.py](../backend/app/api/routes/simulate.py) (lines 1025+)
- **저장소 디렉토리**: [backend/app/storage/local_levels/](../backend/app/storage/local_levels/)
- **생성 도구**: [generate_benchmark_levels.py](../generate_benchmark_levels.py)
- **생성 가이드**: [LEVEL_GENERATION_GUIDE.md](LEVEL_GENERATION_GUIDE.md)
- **자동화 요약**: [AUTOMATION_SUMMARY.md](AUTOMATION_SUMMARY.md)

---

**작성자**: Claude Sonnet 4.5
**문서 버전**: 1.0
**마지막 업데이트**: 2025-12-22
