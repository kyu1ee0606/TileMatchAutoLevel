# TileMatch 맵 에디터 - 실행 방법

## 빠른 시작

### Mac 사용자
👉 **`맵에디터_실행(Mac).command`** 더블클릭

### Windows 사용자
👉 **`맵에디터_실행(Windows).bat`** 더블클릭

---

## 사전 설치 필요

실행 전 아래 프로그램을 먼저 설치하세요:

### 1. Node.js
- 다운로드: https://nodejs.org
- **LTS 버전** 선택 (숫자가 짝수인 버전)
- 설치 후 터미널에서 `node --version` 으로 확인

### 2. Python
- 다운로드: https://python.org
- **Python 3.11 이상** 버전
- ⚠️ **Windows**: 설치 시 **"Add Python to PATH"** 반드시 체크!
- 설치 후 터미널에서 `python3 --version` (Mac) 또는 `python --version` (Windows)으로 확인

---

## 실행 후

1. 자동으로 브라우저가 열립니다
2. 주소: http://localhost:5173
3. 맵 에디터 화면이 나타납니다

### 안 열리면?
- 직접 브라우저에서 http://localhost:5173 접속

---

## 종료 방법

### Mac
- 터미널 창 닫기
- 또는 `Ctrl + C`

### Windows
- 열린 콘솔 창들 모두 닫기
- 또는 작업관리자에서 `node.exe`, `python.exe` 종료

---

## 문제 해결

### "Node.js가 설치되어 있지 않습니다"
→ https://nodejs.org 에서 LTS 버전 설치

### "Python이 설치되어 있지 않습니다"
→ https://python.org 에서 설치
→ Windows: "Add Python to PATH" 체크 확인

### 포트 충돌 (8000 또는 5173)
→ 해당 포트를 사용하는 프로그램 종료 후 재실행

### 최초 실행이 느림
→ 패키지 설치 중입니다 (1-2분 소요, 최초 1회만)

---

## 폴더 구조

```
TileMatchAutoLevel/
├── 맵에디터_실행(Mac).command    ← Mac 실행 파일
├── 맵에디터_실행(Windows).bat   ← Windows 실행 파일
├── README_실행방법.md           ← 이 파일
├── backend/                     ← 서버 코드
└── frontend/                    ← 에디터 UI 코드
```
