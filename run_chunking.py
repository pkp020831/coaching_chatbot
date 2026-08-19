#!/usr/bin/env python3
"""2단계: 수업 대본을 파싱·청킹하고 단순 품질 기준으로 검증한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.chunking import build_chunks, load_transcript


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="화학 수업 대본(.md/.txt/.json)을 발화 단위로 파싱하고 청킹합니다."
    )
    parser.add_argument("transcript", type=Path, help="전사 완료된 대본 파일")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/stage2"),
        help="2단계 결과 폴더 (기본값: artifacts/stage2)",
    )
    parser.add_argument(
        "--target-chars",
        type=int,
        default=700,
        help="청크 목표 최대 글자 수 (기본값: 700)",
    )
    parser.add_argument(
        "--overlap-turns",
        type=int,
        default=1,
        help="인접 청크 사이에 겹칠 발화 수 (기본값: 1)",
    )
    return parser.parse_args()


def evaluate(metrics: dict[str, Any]) -> dict[str, Any]:
    """2단계의 핵심 실패만 잡는 작고 명확한 기준을 적용한다."""
    parse_rate = metrics.get(
        "line_parse_rate",
        metrics.get("segment_parse_rate", 1.0 if metrics.get("parsed_lines") else 0.0),
    )
    checks = [
        {
            "name": "parse_rate",
            "description": "입력 발화 파싱률",
            "actual": parse_rate,
            "criterion": ">= 0.99",
            "passed": parse_rate >= 0.99,
        },
        {
            "name": "source_turn_coverage_rate",
            "description": "원본 발화가 하나 이상의 청크에 포함된 비율",
            "actual": metrics["source_turn_coverage_rate"],
            "criterion": "= 1.00",
            "passed": metrics["source_turn_coverage_rate"] == 1.0,
        },
        {
            "name": "empty_chunk_rate",
            "description": "내용이 비어 있는 청크 비율",
            "actual": metrics["empty_chunk_rate"],
            "criterion": "= 0.00",
            "passed": metrics["empty_chunk_rate"] == 0.0,
        },
        {
            "name": "oversize_chunk_rate",
            "description": "목표 최대 글자 수를 넘은 청크 비율",
            "actual": metrics["oversize_chunk_rate"],
            "criterion": "<= 0.05",
            "passed": metrics["oversize_chunk_rate"] <= 0.05,
        },
        {
            "name": "duplicate_text_rate",
            "description": "완전히 같은 청크가 중복된 비율",
            "actual": metrics["duplicate_text_rate"],
            "criterion": "= 0.00",
            "passed": metrics["duplicate_text_rate"] == 0.0,
        },
    ]
    return {
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "checks": checks,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        transcript = load_transcript(args.transcript)
        chunks, metrics = build_chunks(
            transcript,
            target_chars=args.target_chars,
            overlap_turns=args.overlap_turns,
        )
        evaluation = evaluate(metrics)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    output_dir = args.output_dir.expanduser().resolve()
    base_name = transcript.path.stem
    chunks_path = output_dir / f"{base_name}.chunks.json"
    metrics_path = output_dir / f"{base_name}.metrics.json"
    write_json(
        chunks_path,
        {
            "stage": 2,
            "source_file": transcript.path.name,
            "source_metadata": transcript.metadata,
            "chunking_config": {
                "target_chars": args.target_chars,
                "overlap_turns": args.overlap_turns,
            },
            "chunks": chunks,
        },
    )
    write_json(metrics_path, {"stage": 2, "metrics": metrics, "evaluation": evaluation})

    print(f"2단계 결과: {evaluation['status']}")
    print(f"발화 {metrics['source_turn_count']}개 -> 청크 {metrics['chunk_count']}개")
    print(
        "청크 글자 수: "
        f"평균 {metrics['mean_chunk_chars']}, 중앙값 {metrics['median_chunk_chars']}, "
        f"95백분위 {metrics['p95_chunk_chars']}"
    )
    for check in evaluation["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"[{mark}] {check['name']}: {check['actual']} ({check['criterion']})")
    for warning in metrics["warnings"]:
        print(f"[입력 경고] {warning}")
    print(f"청크: {chunks_path}")
    print(f"평가: {metrics_path}")
    return 0 if evaluation["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
