#!/usr/bin/env python3
"""2단계 청크를 메타데이터와 함께 SQLite DB에 적재하고 검증한다."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.database import ingest_stage2_artifact, validate_lesson


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="2단계 청크를 화학 수업 SQLite DB에 저장합니다.")
    parser.add_argument("chunks", type=Path, help="run_chunking.py가 생성한 *.chunks.json")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/lessons.sqlite3"),
        help="SQLite DB 경로 (기본값: data/lessons.sqlite3)",
    )
    parser.add_argument("--lesson-id", help="수업 ID 직접 지정(기본값: 수업 날짜+파일명)")
    parser.add_argument("--subject", default="화학", help="과목명 (기본값: 화학)")
    parser.add_argument(
        "--metrics-dir",
        type=Path,
        default=Path("artifacts/stage3"),
        help="검증 지표 폴더 (기본값: artifacts/stage3)",
    )
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        ingestion = ingest_stage2_artifact(
            args.chunks,
            args.database,
            lesson_id=args.lesson_id,
            subject=args.subject,
        )
        validation = validate_lesson(
            Path(ingestion["database_path"]),
            ingestion["lesson_id"],
            ingestion["enriched_chunks"],
        )
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    metrics = {
        "stage": 3,
        "database_type": "SQLite",
        "database_path": ingestion["database_path"],
        "lesson_id": ingestion["lesson_id"],
        "previous_chunk_count_replaced": ingestion["previous_chunk_count_replaced"],
        "validation": validation,
    }
    metrics_path = args.metrics_dir.expanduser().resolve() / f"{ingestion['lesson_id']}.metrics.json"
    write_json(metrics_path, metrics)

    print(f"3단계 결과: {validation['status']}")
    print(f"수업 ID: {ingestion['lesson_id']}")
    print(f"적재 청크: {ingestion['expected_chunk_count']}개")
    print(f"교체한 기존 청크: {ingestion['previous_chunk_count_replaced']}개")
    for check in validation["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['actual']} ({check['criterion']})")
    print(f"주제 분포: {validation['topic_distribution']}")
    print(f"문제 번호: {validation['lesson_totals']['question_numbers']}")
    print(f"DB: {ingestion['database_path']}")
    print(f"평가: {metrics_path}")
    return 0 if validation["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
