# TileMatchAutoLevel 배포 가이드

## 배포 현황

| 서비스 | URL | 플랫폼 |
|--------|-----|--------|
| **Frontend** | https://tile-match-auto-level.vercel.app | Vercel |
| **Backend** | https://tilematch-api.onrender.com | Render |

---

## 기술 스택

### Backend (Python)
- **Framework**: FastAPI
- **Server**: Uvicorn
- **주요 라이브러리**: Pydantic, aiohttp, Pillow

### Frontend (TypeScript)
- **Framework**: React 18
- **Build Tool**: Vite
- **상태 관리**: Zustand, TanStack Query

---

## 환경 변수

### Render (Backend)
| 변수명 | 값 | 설명 |
|--------|-----|------|
| `CORS_ORIGINS` | `["https://tile-match-auto-level.vercel.app"]` | 허용된 프론트엔드 도메인 |
| `DEBUG` | `false` | 디버그 모드 |
| `GBOOST_URL` | (선택) | GBoost 서버 URL |
| `GBOOST_PROJECT_ID` | (선택) | GBoost 프로젝트 ID |

### Vercel (Frontend)
| 변수명 | 값 | 설명 |
|--------|-----|------|
| `VITE_API_URL` | `https://tilematch-api.onrender.com/api` | 백엔드 API URL |

---

## 배포 명령어

### Render 설정
- **Root Directory**: `backend`
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Vercel 설정
- **Root Directory**: `frontend`
- **Framework Preset**: Vite
- **Build Command**: `npm run build`
- **Output Directory**: `dist`

---

## 로컬 개발 환경

```bash
# 백엔드 실행
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# 프론트엔드 실행 (새 터미널)
cd frontend
npm run dev
```

로컬 접속: http://localhost:5173

---

## 무료 티어 제한사항

### Render (무료)
- 750시간/월 실행 시간
- **15분 미사용 시 슬립** → 재시작 30초~2분 소요
- 512MB 메모리

### Vercel (무료)
- 100GB/월 대역폭
- 제한 거의 없음

---

## 문제 해결

### 첫 접속이 느린 경우
Render 무료 티어 슬립 상태에서 깨어나는 중. 30초~2분 대기 후 정상 작동.

### CORS 에러 발생 시
Render 환경 변수 `CORS_ORIGINS`에 프론트엔드 URL이 정확히 포함되어 있는지 확인.

### API 연결 실패 시
Vercel 환경 변수 `VITE_API_URL`이 올바른지 확인. 끝에 `/api` 포함 필요.

---

## 업데이트 배포

코드 변경 후 `main` 브랜치에 푸시하면 자동 배포됨:

```bash
git add .
git commit -m "변경 내용"
git push origin main
```

- Render: 자동 재배포 (2-3분)
- Vercel: 자동 재배포 (1분)
