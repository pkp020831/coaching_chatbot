#!/usr/bin/env python3
"""BM25 검색 근거를 사용해 Gemini 서술형 답변을 출력한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lesson_chatbot.answering import answer_question, create_gemini_client_from_env
from lesson_chatbot.gemini_client import GeminiAPIError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="5단계 Gemini 화학 수업 챗봇")
    parser.add_argument("question", help="학생 질문")
    parser.add_argument("--database", type=Path, default=Path("data/lessons.sqlite3"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="전체 JSON 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        client = create_gemini_client_from_env()
        result = answer_question(args.database, args.question, client=client, top_k=args.top_k)
    except (ValueError, OSError, RuntimeError, GeminiAPIError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(result["answer"])
    if result["evidence"]:
        print("\n근거:")
        for row in result["evidence"]:
            print(f"- {row['chunk_id']} (원본 {row['source_line_start']}–{row['source_line_end']}줄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
