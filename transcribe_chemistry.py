#!/usr/bin/env python3
"""Gemini API로 한국어 화학 수업 음성을 JSON/TXT 대본으로 전사한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gemini-3.6-flash"

SUPPORTED_AUDIO_MIME_TYPES = {
    ".aac": "audio/aac",
    ".aiff": "audio/aiff",
    ".flac": "audio/flac",
    ".m4a": "audio/m4a",
    ".mp3": "audio/mp3",
    ".mpeg": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
}

DEFAULT_CHEMISTRY_KEYWORDS = [
    "원자",
    "분자",
    "이온",
    "양이온",
    "음이온",
    "양성자",
    "중성자",
    "전자",
    "원자 번호",
    "질량수",
    "원자량",
    "분자량",
    "몰",
    "몰수",
    "몰 질량",
    "몰 농도",
    "아보가드로수",
    "화학식",
    "분자식",
    "실험식",
    "화학 반응식",
    "반응 계수",
    "한계 반응물",
    "수득률",
    "산화",
    "환원",
    "산화수",
    "산화제",
    "환원제",
    "산",
    "염기",
    "수소 이온 농도",
    "pH",
    "pOH",
    "중화 반응",
    "적정",
    "당량점",
    "종말점",
    "완충 용액",
    "용질",
    "용매",
    "용액",
    "용해도",
    "침전",
    "전해질",
    "비전해질",
    "공유 결합",
    "이온 결합",
    "금속 결합",
    "전기 음성도",
    "극성",
    "비극성",
    "수소 결합",
    "오비탈",
    "전자 배치",
    "주기율표",
    "엔탈피",
    "엔트로피",
    "깁스 자유 에너지",
    "활성화 에너지",
    "촉매",
    "화학 평형",
    "평형 상수",
    "르샤틀리에 원리",
    "반응 속도",
    "이상 기체",
    "보일 법칙",
    "샤를 법칙",
    "기체 상수",
    "켈빈",
    "섭씨",
    "H2O",
    "CO2",
    "O2",
    "H2",
    "N2",
    "NaCl",
    "HCl",
    "H2SO4",
    "HNO3",
    "NaOH",
    "KOH",
    "NH3",
    "CH4",
    "CaCO3",
    "AgNO3",
    "mol/L",
    "g/mol",
    "kJ/mol",
]

TRANSCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {
            "type": "string",
            "description": "오디오에서 주로 사용된 언어의 ISO-639-1 코드",
        },
        "segments": {
            "type": "array",
            "description": "시간 순서대로 정렬된 모든 발화 구간",
            "items": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": "구간 시작 시각. HH:MM:SS.mmm 형식",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "구간 종료 시각. HH:MM:SS.mmm 형식",
                    },
                    "speaker": {
                        "type": "string",
                        "description": "일관된 화자 표시. 예: 화자 1, 화자 2",
                    },
                    "text": {
                        "type": "string",
                        "description": "요약하거나 바꾸지 않은 해당 구간의 발화 내용",
                    },
                },
                "required": ["start_time", "end_time", "speaker", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["language", "segments"],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gemini API로 화학 수업 음성을 한국어 대본으로 전사합니다."
    )
    parser.add_argument("audio", type=Path, help="전사할 음성 파일")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("transcripts"),
        help="결과 폴더 (기본값: transcripts)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini 모델 (기본값: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--language",
        default="ko",
        help="예상 언어 ISO-639-1 코드 (기본값: ko)",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="이번 수업의 핵심 용어. 여러 번 지정 가능",
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        help="추가 용어집. UTF-8 텍스트 또는 JSON 문자열 배열",
    )
    parser.add_argument(
        "--no-default-keywords",
        action="store_true",
        help="내장 화학 용어를 사용하지 않음",
    )
    parser.add_argument("--force", action="store_true", help="기존 결과 덮어쓰기")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API를 호출하거나 비용을 발생시키지 않고 설정만 검사",
    )
    return parser.parse_args()


def validate_audio(path: Path) -> tuple[Path, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"음성 파일을 찾을 수 없습니다: {path}")
    if resolved.stat().st_size == 0:
        raise ValueError("음성 파일이 비어 있습니다.")

    mime_type = SUPPORTED_AUDIO_MIME_TYPES.get(resolved.suffix.lower())
    if mime_type is None:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_MIME_TYPES))
        raise ValueError(f"지원하지 않는 형식입니다: {resolved.suffix} (지원: {supported})")
    return resolved, mime_type


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"용어집 파일을 찾을 수 없습니다: {path}")

    raw = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".json":
        values = json.loads(raw)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("JSON 용어집은 문자열 배열이어야 합니다.")
        return values

    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def unique_normalized_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = unicodedata.normalize("NFC", term).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def build_prompt(language: str, keywords: list[str]) -> str:
    glossary = ", ".join(keywords)
    return f"""
당신은 화학 수업 전문 음성 전사기입니다. 첨부된 전체 음성을 {language} 언어로 전사하세요.

반드시 지킬 규칙:
1. 모든 발화를 시간 순서대로 빠짐없이 전사하고 요약하거나 해설하지 마세요.
2. 발음만으로 확신할 수 없는 내용은 추측하지 말고 [불명확]이라고 표시하세요.
3. 화자를 구분할 수 있으면 '화자 1', '화자 2'처럼 끝까지 일관되게 표시하세요.
4. 각 구간에 정확한 시작·종료 시각을 HH:MM:SS.mmm 형식으로 기록하세요.
5. 화학식, 숫자, 단위, 원소명, 반응식은 특히 주의해서 전사하세요.
6. 아래 용어는 철자 힌트일 뿐입니다. 실제 음성에서 들리지 않은 용어를 추가하지 마세요.
7. 결과에는 대본 외의 요약, 평가, 설명을 포함하지 마세요.

화학 용어 후보:
{glossary}
""".strip()


def parse_timestamp(value: str) -> float:
    cleaned = value.strip().strip("[]").replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"잘못된 타임스탬프 형식: {value}")

    total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if total < 0:
        raise ValueError(f"음수 타임스탬프: {value}")
    return round(total, 3)


def normalize_transcription(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Gemini 응답에 전사 구간이 없습니다.")

    segments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise ValueError(f"{index}번 전사 구간이 JSON 객체가 아닙니다.")

        text = str(raw.get("text", "")).strip()
        if not text:
            raise ValueError(f"{index}번 전사 구간의 텍스트가 비어 있습니다.")

        start_sec = parse_timestamp(str(raw.get("start_time", "")))
        end_sec = parse_timestamp(str(raw.get("end_time", "")))
        if end_sec < start_sec:
            raise ValueError(f"{index}번 구간의 종료 시각이 시작 시각보다 빠릅니다.")

        segments.append(
            {
                "segment_id": f"seg_{index:06d}",
                "start_sec": start_sec,
                "end_sec": end_sec,
                "speaker": str(raw.get("speaker", "화자 미상")).strip() or "화자 미상",
                "text": text,
            }
        )

    language = str(payload.get("language", "ko")).strip() or "ko"
    return language, segments


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def write_text_transcript(path: Path, segments: list[dict[str, Any]]) -> None:
    lines = [
        f"[{format_timestamp(item['start_sec'])} - {format_timestamp(item['end_sec'])}] "
        f"[{item['speaker']}] {item['text']}"
        for item in segments
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return str(value)


def existing_output_matches(
    path: Path,
    source_hash: str,
    model: str,
    language: str,
    keywords: list[str],
) -> bool:
    if not path.is_file():
        return False
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        metadata = saved.get("transcription", {})
        return all(
            (
                saved.get("source", {}).get("sha256") == source_hash,
                metadata.get("provider") == "google-gemini",
                metadata.get("model") == model,
                metadata.get("requested_language") == language,
                metadata.get("keywords") == keywords,
            )
        )
    except (OSError, json.JSONDecodeError):
        return False


def main() -> int:
    args = parse_args()
    try:
        audio_path, mime_type = validate_audio(args.audio)
        glossary_terms = load_glossary(args.glossary)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    base_terms = [] if args.no_default_keywords else DEFAULT_CHEMISTRY_KEYWORDS
    keywords = unique_normalized_terms(base_terms + glossary_terms + args.topic)
    source_hash = sha256_file(audio_path)
    output_dir = args.output_dir.expanduser().resolve()
    json_path = output_dir / f"{audio_path.stem}.transcript.json"
    text_path = output_dir / f"{audio_path.stem}.transcript.txt"

    print(f"입력: {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"제공자/모델: Google Gemini / {args.model}")
    print(f"언어/화학 키워드: {args.language} / {len(keywords)}개")
    print(f"출력: {json_path}")

    if args.dry_run:
        print("설정 검증 완료 (--dry-run: 파일 업로드와 API 호출을 하지 않았습니다).")
        return 0

    try:
        from dotenv import load_dotenv
        from google import genai
    except ImportError:
        print(
            "오류: 필요한 패키지가 없습니다. "
            "'python3 -m pip install -r requirements.txt'를 실행해 주세요.",
            file=sys.stderr,
        )
        return 2

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("오류: .env 또는 환경변수에 GEMINI_API_KEY를 설정해 주세요.", file=sys.stderr)
        return 2

    if (
        existing_output_matches(json_path, source_hash, args.model, args.language, keywords)
        and not args.force
    ):
        print("동일한 음성과 설정의 전사 결과가 이미 있어 건너뜁니다. (--force로 재실행)")
        return 0
    if json_path.exists() and not args.force:
        print(f"오류: 결과가 이미 있습니다: {json_path} (--force로 덮어쓰기)", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)
    uploaded_file = None
    interaction = None
    api_error: Exception | None = None
    uploaded_file_deleted = False
    started = time.monotonic()

    try:
        print("음성 파일을 Gemini Files API에 업로드합니다...")
        uploaded_file = client.files.upload(
            file=str(audio_path),
            config={"mime_type": mime_type},
        )
        print("전사를 시작합니다...")
        interaction = client.interactions.create(
            model=args.model,
            input=[
                {"type": "text", "text": build_prompt(args.language, keywords)},
                {
                    "type": "audio",
                    "uri": uploaded_file.uri,
                    "mime_type": uploaded_file.mime_type or mime_type,
                },
            ],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": TRANSCRIPTION_SCHEMA,
            },
        )
    except Exception as error:
        api_error = error
    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(name=uploaded_file.name)
                uploaded_file_deleted = True
                print("Gemini에 임시 업로드한 음성 파일을 삭제했습니다.")
            except Exception as cleanup_error:
                print(f"경고: 임시 업로드 파일 삭제 실패: {cleanup_error}", file=sys.stderr)

    if api_error is not None:
        print(f"Gemini 전사 API 호출 실패: {api_error}", file=sys.stderr)
        return 1
    if interaction is None or not getattr(interaction, "output_text", None):
        print("Gemini가 빈 응답을 반환하여 결과를 저장하지 않았습니다.", file=sys.stderr)
        return 1

    try:
        payload = json.loads(interaction.output_text)
        detected_language, segments = normalize_transcription(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"Gemini 전사 응답 검증 실패: {error}", file=sys.stderr)
        return 1

    elapsed = round(time.monotonic() - started, 3)
    transcript_text = "\n".join(item["text"] for item in segments)
    usage = jsonable(getattr(interaction, "usage", None))
    duration = segments[-1]["end_sec"]

    result = {
        "schema_version": "1.0",
        "transcript_id": f"{audio_path.stem}_{source_hash[:16]}",
        "source": {
            "filename": audio_path.name,
            "path": str(audio_path),
            "mime_type": mime_type,
            "size_bytes": audio_path.stat().st_size,
            "sha256": source_hash,
        },
        "transcription": {
            "provider": "google-gemini",
            "model": args.model,
            "requested_language": args.language,
            "detected_language": detected_language,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "duration_seconds": duration,
            "keywords": keywords,
            "usage": usage,
            "uploaded_file_deleted": uploaded_file_deleted,
        },
        "text": transcript_text,
        "segments": segments,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_text_transcript(text_path, segments)

    print(f"완료: {elapsed:.1f}초, 구간 {len(segments)}개")
    print(f"JSON: {json_path}")
    print(f"TXT:  {text_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
