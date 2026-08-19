# 수업 대본 입력 폴더

전사가 완료된 수업 대본을 이 폴더에 넣습니다. 학생 개인정보가 포함될 수 있으므로
이 폴더의 실제 대본과 음성 파일은 Git에 올라가지 않습니다.

지원 형식:

- Markdown: `**선생님:** 내용`
- TXT: `[00:00:00.000 - 00:00:05.000] [화자 1] 내용`
- JSON: `segments` 배열 안에 `speaker`, `text`, 선택적 시간 정보

예를 들어 `source/my_lesson.md`를 넣었다면 프로젝트 최상위 폴더에서 실행합니다.

```bash
python3 run_chunking.py source/my_lesson.md
python3 build_database.py artifacts/stage2/my_lesson.chunks.json
```
