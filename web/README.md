# 화학 수업 챗봇 웹 화면

Python 검색·답변 API를 학생이 사용할 수 있는 웹 화면으로 보여주는 Vinext 앱입니다.
프로젝트 전체 설치 방법은 상위 폴더의 `README.md`를 먼저 읽어 주세요.

## 처음 한 번만 설치

```bash
cd web
npm install
```

## 실행

먼저 프로젝트 최상위 폴더의 다른 터미널에서 Python API를 실행합니다.

```bash
python3 serve_search_web.py
```

Windows에서는 프로젝트 최상위 폴더에서 다음 스크립트를 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1
```

그다음 이 폴더에서 웹 서버를 실행합니다.

macOS 또는 Linux:

```bash
npm run dev
```

Windows에서는 두 번째 PowerShell을 열고 프로젝트 최상위 폴더에서 다음 스크립트를
실행해도 됩니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_windows.ps1
```

`web` 폴더 안에서 직접 실행하려면 Windows 전용 명령을 사용합니다.

```powershell
npm run dev:windows
```

브라우저에서 `http://localhost:3000/`을 엽니다. Python API는
`http://127.0.0.1:8765`에서 실행되어야 합니다.

## 검사

```bash
npm run lint
npm test
```

답변 생성 시 학생 질문과 BM25가 선택한 상위 수업 근거가 Gemini API로 전송됩니다.
API 키는 웹 코드가 아닌 프로젝트 최상위 폴더의 `.env`에만 저장합니다.
