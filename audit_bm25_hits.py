#!/usr/bin/env python3
"""BM25 정답 적중이 우연인지 문항별로 안정성과 무작위 기준선을 검사한다."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.audit import audit_bm25_hits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BM25 적중의 근거와 안정성을 감사합니다.")
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path("bm25_eval_dataset_20.json"),
        help="평가 JSON",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/lessons.sqlite3"),
        help="SQLite DB 경로",
    )
    parser.add_argument("--top-k", type=int, default=5, help="감사할 Top-k (기본값: 5)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/stage4/bm25_hit_audit.json"),
        help="감사 결과 JSON",
    )
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        result = audit_bm25_hits(
            args.database,
            args.dataset,
            top_k=args.top_k,
        )
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    output_path = args.output.expanduser().resolve()
    write_json(output_path, result)
    summary = result["summary"]
    print(f"문항: {result['question_count']}개 / Top-{result['top_k']}")
    print(f"판정: {summary['classification_counts']}")
    print(
        f"실제/무작위 기대 Top-1 적중: {summary['observed_top1_hits']} / "
        f"{summary['random_expected_top1_hits']}"
    )
    print(
        f"실제/무작위 기대 Top-{result['top_k']} 적중: {summary['observed_top_k_hits']} / "
        f"{summary['random_expected_top_k_hits']}"
    )
    print(
        f"무작위 이상 적중 확률: Top-1={summary['random_tail_probability_top1']:.3e}, "
        f"Top-{result['top_k']}={summary['random_tail_probability_top_k']:.3e}"
    )
    print(f"평균 단어 제거 안정성: {summary['mean_leave_one_token_out_stability']:.4f}")
    for item in result["per_question"]:
        print(
            f"{item['id']}: {item['classification']} | rank={item['first_relevant_rank']} | "
            f"안정성={item['leave_one_token_out']['stability']:.2f} | "
            f"동일어절={item['distinctive_exact_matches']}"
        )
    print(f"상세 결과: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
