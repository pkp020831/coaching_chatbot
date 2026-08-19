#!/usr/bin/env python3
"""화학 수업 SQLite DB에서 BM25 상위 k개 청크를 검색한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.retrieval import search_bm25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="화학 수업 청크를 SQLite BM25로 검색합니다.")
    parser.add_argument("query", help="학생의 질문 또는 검색어")
    parser.add_argument("--top-k", type=int, default=5, help="반환할 최대 청크 수 (기본값: 5)")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/lessons.sqlite3"),
        help="SQLite DB 경로 (기본값: data/lessons.sqlite3)",
    )
    parser.add_argument("--lesson-id", help="특정 수업으로 한정")
    parser.add_argument("--topic", help="주제 태그로 한정")
    parser.add_argument("--question-number", type=int, help="문제 번호로 한정")
    parser.add_argument("--show-chars", type=int, default=350, help="화면에 보여줄 본문 글자 수")
    parser.add_argument("--json", action="store_true", help="검색 결과 전체를 JSON으로 출력")
    parser.add_argument(
        "--metrics-dir",
        type=Path,
        default=Path("artifacts/stage4"),
        help="운영 지표 폴더 (기본값: artifacts/stage4)",
    )
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def one_line(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}…"


def main() -> int:
    args = parse_args()
    try:
        result = search_bm25(
            args.database,
            args.query,
            top_k=args.top_k,
            lesson_id=args.lesson_id,
            topic=args.topic,
            question_number=args.question_number,
        )
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    query_hash = hashlib.sha256(args.query.encode("utf-8")).hexdigest()[:12]
    metrics_path = args.metrics_dir.expanduser().resolve() / f"query_{query_hash}.metrics.json"
    write_json(metrics_path, {"stage": 4, "search_type": "SQLite FTS5 BM25", **result})

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"BM25 검색 결과: {result['returned_count']}/{args.top_k}개")
    print(
        f"후보 {result['candidate_count']}개, 질의 {result['query_latency_ms']}ms, "
        f"인덱스 {'재생성' if result['index']['rebuilt'] else '최신'} "
        f"({result['index']['index_build_ms']}ms)"
    )
    for item in result["results"]:
        print(
            f"\n{item['rank']}. score={item['score']} | {item['lesson_id']} "
            f"/ 청크 {item['chunk_index']} / 원본 줄 {item['source_line_start']}-{item['source_line_end']}"
        )
        print(f"   주제: {', '.join(item['topics'])} | 문제: {item['question_numbers'] or '-'}")
        print(f"   {one_line(item['text'], args.show_chars)}")
    print(f"\n운영 지표: {metrics_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
