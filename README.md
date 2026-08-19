# 화학 수업 챗봇 파이프라인

ZOOM으로 화학 과외를 진행하고 있다.
이 수업 녹화영상을 전사하여 해당 수업 관련 질문을 받아주는 챗봇을 제작하고자 한다.

# 파이프라인

1단계 Gemini api로 음성파일 전사 (현재는 생략)
2단계 파싱·청킹
3단계 메타데이터 SQLite -> DB 저장
4단계 BM25 검색
5단계 Gemini 서술형 답변 + 평가 LLM을 배치하여 피드백 (현재는 구현하지 못함)

음성파일은 용량이 크고 전사가 오래걸리므로 시간관계상 전사 완료된 대본으로 진행

## GitHub에서 처음 시작하기

### 1. 준비 사항

- Python 3.10 이상
- Node.js 22.13 이상
- Google Gemini API 키
- 전사가 완료된 수업 대본(Markdown, TXT 또는 JSON)

학생 음성, 대본 처리 결과, SQLite DB와 실제 API 키는 개인정보 보호를 위해 Git에
올라가지 않습니다. 따라서 처음 클론한 사용자는 자신의 대본으로 2·3단계를 한 번
실행해 DB를 만들어야 합니다.

### 2. Windows에서 가장 간단하게 설치하기

Windows에서는 **PowerShell**을 열고 저장소를 클론한 뒤 아래 명령을 실행합니다.

```powershell
git clone <저장소-URL>
cd <클론된-폴더명>
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

이 스크립트가 Python 가상환경 생성, Python 패키지 설치, `.env` 생성, 웹 패키지
설치를 차례대로 처리합니다. 가상환경을 직접 활성화할 필요도 없습니다. 설치 후 `.env`를
메모장이나 VS Code로 열어 `GEMINI_API_KEY`만 입력하세요.

그다음 PowerShell 창을 두 개 열고 프로젝트 폴더에서 각각 실행합니다.

```powershell
# 첫 번째 PowerShell: 검색·답변 API
powershell -ExecutionPolicy Bypass -File .\scripts\start_api_windows.ps1
```

```powershell
# 두 번째 PowerShell: 웹 화면
powershell -ExecutionPolicy Bypass -File .\scripts\start_web_windows.ps1
```

Windows에서 웹 폴더로 직접 이동해 실행하려면 `npm run dev:windows`를 사용합니다.
macOS·Linux의 기존 `npm run dev` 명령도 그대로 유지됩니다.

브라우저에서 `http://localhost:3000/`을 엽니다. Windows 보안 경고가 표시되면
**개인 네트워크**에서만 Python과 Node.js의 통신을 허용하세요.

### 3. macOS 또는 Linux에서 설치하기

```bash
git clone <저장소-URL>
cd <클론된-폴더명>

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 4. Gemini API 키 설정

실제 키를 `.env.example`에 입력하면 안 됩니다. `.env.example`은 GitHub에 올라가는
공개 설정 양식이고, 실제 키는 Git에서 제외되는 `.env`에만 저장합니다.

macOS 또는 Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

복사해서 만든 `.env`를 텍스트 편집기로 열고 다음처럼 입력합니다.

```env
GEMINI_API_KEY=실제_API_키
GEMINI_MODEL=gemini-3.6-flash
GEMINI_EVALUATOR_MODEL=gemini-3.6-flash
```

- `GEMINI_API_KEY=` 앞뒤에 공백을 넣지 않습니다.
- `.env`와 API 키를 Git에 커밋하거나 다른 사람에게 전송하지 않습니다.
- `.env.example`의 `GEMINI_API_KEY=`는 계속 빈 상태로 둡니다.
- 키를 실수로 GitHub에 올렸다면 즉시 해당 키를 폐기하고 새 키를 발급받습니다.

### 5. 자신의 수업 대본으로 DB 생성

대본을 `source/`에 넣은 뒤 실행합니다. 다음 예시는 파일명이 `my_lesson.md`인 경우입니다.

```bash
python3 run_chunking.py source/my_lesson.md
python3 build_database.py artifacts/stage2/my_lesson.chunks.json
```

Windows PowerShell에서는 다음처럼 실행합니다. Windows 설치 스크립트를 사용했다면
가상환경 활성화 없이 그대로 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe run_chunking.py source\my_lesson.md
.\.venv\Scripts\python.exe build_database.py artifacts\stage2\my_lesson.chunks.json
```

정상적으로 완료되면 `data/lessons.sqlite3`가 생성됩니다.

### 6. 웹 패키지 설치

```bash
cd web
npm install
cd ..
```

### 7. 챗봇 실행

첫 번째 터미널에서 검색·답변 API를 실행합니다.

```bash
source .venv/bin/activate
python3 serve_search_web.py
```

두 번째 터미널에서 웹 화면을 실행합니다.

```bash
cd web
npm run dev
```

Windows PowerShell에서 수동으로 실행하는 경우에는 다음 명령을 사용합니다.

```powershell
cd web
npm run dev:windows
```

브라우저에서 `http://localhost:3000/`을 엽니다. API 설정 상태는 다음 주소에서도
확인할 수 있습니다.

```bash
curl http://127.0.0.1:8765/health
```

Windows PowerShell에서는 다음 명령으로 확인합니다.

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

응답의 `"gemini_configured": true`가 확인되면 API 키가 정상적으로 읽힌 것입니다.
`.env`를 수정했다면 실행 중인 Python API 서버를 `Ctrl+C`로 종료한 뒤 다시
실행해야 합니다.

웹을 띄우기 전에 다음 명령으로 답변 생성만 확인할 수도 있습니다.

```bash
python3 answer_with_llm.py "열용량이 무엇인가요?"
```

Windows에서는 `python3` 대신 `.\.venv\Scripts\python.exe`를 사용하면 됩니다.

### Windows 수동 설치가 필요한 경우

자동 설치 스크립트를 사용하지 않으려면 PowerShell에서 아래 명령을 한 줄씩
실행합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
cd web
npm install
cd ..
```

`py` 명령이 없다면 첫 줄의 `py -3`을 `python`으로 바꾸세요. 가상환경 활성화를
원한다면 `.\.venv\Scripts\Activate.ps1`을 실행할 수 있지만 필수는 아닙니다.
활성화가 실행 정책 때문에 차단되면 현재 PowerShell 창에서만 다음 설정을 적용합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Windows에서 자주 발생하는 문제

- `python`, `py` 또는 `npm`을 찾을 수 없다는 메시지: Python이나 Node.js를 설치한
  뒤 **PowerShell을 완전히 닫고 새로 열어** 다시 실행합니다.
- `running scripts is disabled` 메시지: README의
  `powershell -ExecutionPolicy Bypass -File ...` 형태로 실행합니다. 시스템 전체 실행
  정책은 바꿀 필요가 없습니다.
- `Address already in use` 또는 `WinError 10048`: 이미 API가 실행 중인지
  `Invoke-RestMethod http://127.0.0.1:8765/health`로 확인합니다. 정상 응답이면 API를
  다시 실행하지 않아도 됩니다.
- 웹은 열리지만 답변이 나오지 않음: API용 PowerShell과 웹용 PowerShell 두 창이
  모두 실행 중인지, `/health` 응답의 `gemini_configured`가 `True`인지 확인합니다.
- Windows Defender 방화벽 경고: 공용 네트워크에는 허용하지 말고 개인 네트워크에서만
  허용합니다. 이 프로젝트는 `127.0.0.1` 로컬 주소만 사용합니다.

GitHub Actions도 Ubuntu와 Windows에서 Python 테스트, SQLite FTS5 검색 테스트, 웹
빌드·테스트를 각각 실행하도록 설정되어 있습니다.

## 2단계 실행

이 단계는 Python 표준 라이브러리만 사용하므로 패키지 설치가 필요 없습니다.

```bash
python3 run_chunking.py source/audio_transcript_science_class.md
```

기본 설정은 최대 700자, 인접 청크 사이 1개 발화 중복입니다. 설정을 바꾸려면:

```bash
python3 run_chunking.py source/audio_transcript_science_class.md \
  --target-chars 600 \
  --overlap-turns 1
```

입력 형식은 다음 세 가지를 지원합니다.

- Markdown: `**선생님:** 내용` 형식
- TXT: `[00:00:00.000 - 00:00:05.000] [화자 1] 내용` 형식
- JSON: `segments` 배열에 `speaker`, `text`, 선택적 시간 정보가 있는 형식

결과는 `artifacts/stage2/`에 생성됩니다. 학생 발화가 포함되므로 이 폴더는
Git에서 제외됩니다.

```text
artifacts/stage2/<대본명>.chunks.json
artifacts/stage2/<대본명>.metrics.json
```

## 2단계 통과 기준

의미 검색 성능은 아직 평가하지 않습니다. 이번 단계에서는 구조적 손실과 명백한
청킹 오류만 아래 기준으로 검사합니다.

| 지표 | 통과 기준 | 의미 |
|---|---:|---|
| 파싱률 | 99% 이상 | 대본 줄을 발화로 인식한 비율 |
| 원본 발화 포함률 | 100% | 모든 발화가 하나 이상의 청크에 포함됨 |
| 빈 청크 비율 | 0% | 내용 없는 청크가 없음 |
| 최대 크기 초과 비율 | 5% 이하 | 설정한 글자 수를 과도하게 넘지 않음 |
| 완전 중복 청크 비율 | 0% | 동일한 청크가 중복 생성되지 않음 |

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

## 3단계: 메타데이터 SQLite DB

2단계 결과를 DB에 저장합니다.

```bash
python3 build_database.py \
  artifacts/stage2/audio_transcript_science_class.chunks.json
```

기본 DB 경로는 `data/lessons.sqlite3`입니다. SQLite를 사용하므로 별도 DB 서버나
패키지 설치가 필요 없습니다. `data/`에는 학생 이름과 발화가 들어 있으므로
Git에서 제외됩니다.

DB에는 다음 정보가 저장됩니다.

- 수업: 수업 ID, 제목, 날짜, 과목, 언어, 원본 파일, 2단계 결과 해시
- 청크: 순서, 원본 발화·줄·시간 범위, 화자, 본문, 본문 해시
- 검색용 메타데이터: 화학 주제, 화학 용어, 문제 번호, 콘텐츠 유형

같은 수업 ID를 다시 적재하면 기존 청크를 트랜잭션 안에서 교체합니다. 수업 ID는
기본적으로 `수업 날짜_대본 파일명`이며 필요하면 직접 지정할 수 있습니다.

```bash
python3 build_database.py path/to/lesson.chunks.json \
  --lesson-id 2026-08-19-middle-school-chemistry
```

3단계는 다음 기준을 모두 만족해야 통과합니다.

| 지표 | 통과 기준 |
|---|---:|
| SQLite 자체 무결성 검사 | `ok` |
| 외래 키 오류 | 0개 |
| 입력·저장 청크 수 | 완전 일치 |
| 저장 전후 본문 일치율 | 100% |
| 필수 메타데이터 완성률 | 100% |
| 수업 내 청크 순번 중복 | 0개 |

검증 결과는 `artifacts/stage3/<수업 ID>.metrics.json`에 저장됩니다.

## 4단계: BM25 상위 k 검색

학생 질문을 입력하면 상위 k개 청크와 BM25 점수, 수업·주제·문제 번호·원본 줄 위치를
반환합니다.

```bash
python3 search_bm25.py "열용량이 뭔가요?" --top-k 3
```

특정 수업, 주제 또는 문제 번호로도 한정할 수 있습니다.

```bash
python3 search_bm25.py "상태 변화" \
  --lesson-id 2026-08-19_audio_transcript_science_class \
  --question-number 113 \
  --top-k 3
```

검색기는 SQLite FTS5의 `bm25()`를 사용합니다. 첫 검색 시 또는 3단계 DB 내용이
바뀐 경우에만 인덱스를 자동 갱신합니다. 한국어 조사 변화는 화학 용어 어절과 한글
2·3-gram 보조 토큰으로 보완합니다. 예를 들어 `열용량이`라는 질문도 `열용량` 설명을
찾을 수 있습니다.

각 질의의 후보 수, 실제 반환 수, 인덱스 갱신 여부·시간, 질의 지연시간은
`artifacts/stage4/`에 저장됩니다. 이 지표는 검색 시스템의 운영 상태 확인용입니다.

### BM25 평가

정답 청크가 표시된 `bm25_eval_dataset_20.json`으로 평가합니다.

```bash
python3 evaluate_bm25.py
```

다른 k 값도 지정할 수 있습니다.

```bash
python3 evaluate_bm25.py bm25_eval_dataset_20.json \
  --k 1 --k 3 --k 5 --k 10
```

평가 JSON의 용어는 다음과 같이 정의합니다.

| 필드 | 코드에서 사용하는 의미 |
|---|---|
| `id` | `Q01` 형식의 고유 평가 문항 ID |
| `category` | DB 콘텐츠 유형과 같은 `수업 운영·피드백`, `개념 설명`, `문제 풀이`, `교사-학생 대화` 중 하나 |
| `question` | BM25에 그대로 입력하는 학생 질문 |
| `relevant_chunk_ids` | 답변 근거를 포함하는 DB의 완전한 `chunk_id`; 근거가 청크 경계에 걸치면 복수 지정 |
| `target_keywords` | 토큰화와 정답 청크의 어휘 일치를 진단하는 키워드; 검색 질의나 순위 계산에는 사용하지 않음 |
| `gold_answer` | 5단계 LLM 답변 평가용 모범 답안; BM25 검색 평가에는 사용하지 않음 |

평가기는 데이터 필드, 카테고리 용어, 문항 ID 중복, DB에 없는 정답 청크를 먼저
검사한 후 Hit@k, Precision@k, Recall@k, MRR@k, nDCG@k를 계산합니다. 상세 결과는
`artifacts/stage4/bm25_eval.metrics.json`에 저장됩니다.

### 적중 결과 우연성 감사

평가에서 맞힌 문항도 단순 우연이나 정답 힌트 누출로 맞은 것은 아닌지 별도로
감사합니다.

```bash
python3 audit_bm25_hits.py
```

감사기는 다음을 확인합니다.

- `target_keywords`, `gold_answer`가 실제 검색·순위 계산에 사용되지 않았는지
- 질의와 정답 청크 사이에 직접 단어 또는 한글 2·3-gram 근거가 있는지
- 질의 단어를 하나씩 제거해도 정답 청크가 Top-k에 남는지
- 전체 청크에서 무작위로 k개를 뽑았을 때와 비교해 적중 수가 유의하게 높은지

문항별 `강건·보통·취약·실패` 판정과 근거는
`artifacts/stage4/bm25_hit_audit.json`에 저장됩니다.

### 로컬 웹 검색기

학생 이름과 수업 발화를 외부로 보내지 않도록 검색 API와 화면 모두 로컬에서만
실행합니다. 터미널 두 개에서 아래 명령을 각각 실행하세요.

```bash
# 터미널 1: SQLite BM25 검색 API
python3 serve_search_web.py
```

```bash
# 터미널 2: 웹 화면 (최초 한 번은 cd web && npm install)
cd web
npm run dev
```

브라우저에서 `http://localhost:3000/`을 열면 질문과 Top-k를 선택해 근거 청크를
검색할 수 있습니다. 웹 화면의 프로덕션 빌드는 다음 명령으로 검증합니다.

```bash
cd web
npm run build
```

## 보류된 전사 코드

`transcribe_chemistry.py`는 이후 전사 API 단계를 다시 시작할 때 사용할 수 있도록
남겨 두었습니다. 현재 2단계 실행에는 API 키가 필요하지 않습니다.

## 5단계: Gemini 근거 기반 서술형 답변

`.env.example`을 `.env`로 복사한 뒤 `GEMINI_API_KEY`를 설정합니다. 키는 웹 화면에
넣지 않으며 로컬 Python 서버에서만 읽습니다. 답변 생성 시 학생 질문과 BM25가 찾은
상위 청크는 Gemini API로 전송됩니다. 전체 대본을 한꺼번에 보내지는 않습니다.

```bash
python3 answer_with_llm.py "열용량이 무엇인가요?"
```

답변기는 질문을 다음 다섯 범위로 구분합니다.

| 범위 | 처리 방식 |
|---|---|
| `DIRECT_CLASS` | 수업 대본의 직접 근거로 답변 |
| `INFERRED_CLASS` | 직접 답은 아니지만 대본 근거로 가능한 추론임을 밝히고 설명 |
| `RELATED_GENERAL` | 수업에서 직접 다루지 않은 관련 기본 화학 이론임을 밝히고 보충 |
| `COURSE_INFO_MISSING` | 근거 없는 숙제·휴강·일정·출결 정보를 추측하지 않고 확인 요청 |
| `OUT_OF_SCOPE` | 이번 수업과 관련이 없는 질문을 안전하게 거절 |

Gemini가 존재하지 않는 청크 ID를 인용하면 서버가 제거합니다. 특히 운영 정보와 범위
밖 질문은 LLM이 임의 답변을 만들더라도 서버가 고정된 안전 문구로 교체합니다.

### 웹 챗봇

```bash
# 터미널 1
python3 serve_search_web.py

# 터미널 2
cd web && npm run dev
```

`http://localhost:3000/`에서 질문과 Top-k를 선택하면 서술형 답변, 범위 판정,
확신도와 실제 인용 청크를 함께 확인할 수 있습니다.

### 5단계 평가 질문 세트

실제 수업용 `stage5_eval_dataset.json`은 학생 이름과 수업 정보가 포함될 수 있어
Git에서 제외됩니다. 처음 클론한 사용자는 공개된 익명 예제를 복사해 자신의 수업에
맞게 수정합니다.

```bash
cp examples/stage5_eval_dataset.example.json stage5_eval_dataset.json
```

평가 세트에는 다음 다섯 유형을 균형 있게 포함하는 것을 권장합니다.

- 직접 수업 운영
- 직접 개념
- 간접 추론 가능
- 관련 일반화학 보충
- 수업 밖 안전 거절

`gold_answer`, 필수 포함 내용과 금지 주장은 답변 생성이 끝난 후 평가 단계에서만
결합됩니다. BM25 검색 또는 답변 생성 프롬프트에는 전달되지 않습니다. 더 큰 BM25
평가 세트 작성 기준은 `docs/bm25_evaluation_question_set_guide.md`를 참고하세요.

질문 세트의 답변을 일괄 생성합니다. 처음에는 비용 확인을 위해 일부만 실행하는 것이
좋습니다.

```bash
python3 run_stage5_eval.py --limit 3
python3 run_stage5_eval.py
```

### 별도 평가 LLM과 교사 피드백

API 비용 없이 입력과 평가 프롬프트만 먼저 검사할 수 있습니다.

```bash
python3 evaluate_llm_answers.py artifacts/stage5/generated_answers.json --dry-run
python3 evaluate_llm_answers.py artifacts/stage5/generated_answers.json
```

교사는 각 문항을 아래 6개 항목으로 1~5점 채점합니다.

1. `class_grounding`: 수업 근거 충실성
2. `scope_boundary`: 범위 판단과 안전성
3. `correctness_relevance`: 정확성과 관련성
4. `completeness_actionability`: 충분성과 실행 가능성
5. `student_clarity`: 학생 눈높이와 명료성
6. `citation_traceability`: 근거 추적 가능성

```bash
python3 record_teacher_feedback.py \
  artifacts/stage5/llm_answer_eval.json S5Q01 \
  --score class_grounding=5 \
  --score scope_boundary=5 \
  --score correctness_relevance=5 \
  --score completeness_actionability=4 \
  --score student_clarity=5 \
  --score citation_traceability=5 \
  --overall-score 96 --pass \
  --notes "근거와 설명이 명확함"
```

교사 채점은 `artifacts/stage5/teacher_feedback.jsonl`에 누적됩니다. 이후 평가 LLM은
최근 교사 사례를 few-shot 예시로 사용하고, 교사와 평가 LLM의 점수 편향 및 항목
가중치를 보정합니다. 이는 Gemini 모델 자체를 파인튜닝하는 것이 아니라 로컬 평가
기준을 교사 채점에 맞게 점진적으로 보정하는 방식입니다.
