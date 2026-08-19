#!/usr/bin/env python3
"""bm25_eval JSON을 사용해 Recall@k, MRR, nDCG 등을 계산한다."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.evaluation import evaluate_bm25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="정답 청크가 표시된 JSON으로 BM25를 평가합니다.")
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=Path("bm25_eval_dataset_20.json"),
        help="평가 JSON (기본값: bm25_eval_dataset_20.json)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/lessons.sqlite3"),
        help="SQLite DB 경로 (기본값: data/lessons.sqlite3)",
    )
    parser.add_argument(
        "--k",
        type=int,
        action="append",
        dest="k_values",
        help="평가할 k. 여러 번 지정 가능 (기본값: 1, 3, 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/stage4/bm25_eval.metrics.json"),
        help="상세 결과 JSON 경로",
    )
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        result = evaluate_bm25(
            args.database,
            args.dataset,
            k_values=tuple(args.k_values or (1, 3, 5)),
        )
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2

    output_path = args.output.expanduser().resolve()
    write_json(output_path, result)
    print(f"평가 문항: {result['question_count']}개")
    for key, metrics in result["summary"].items():
        print(
            f"{key}: Hit={metrics['hit']:.4f}, Precision={metrics['precision']:.4f}, "
            f"Recall={metrics['recall']:.4f}, MRR={metrics['mrr']:.4f}, nDCG={metrics['ndcg']:.4f}"
        )
    tokenizer = result["tokenizer_validation"]
    print(
        f"키워드 토큰화율: {tokenizer['tokenization_rate']:.4f}, "
        f"정답 청크 어휘 일치율: {tokenizer['relevant_text_lexical_match_rate']:.4f}"
    )
    print(
        f"평균/P95 질의 시간: {result['latency']['mean_query_ms']}ms / "
        f"{result['latency']['p95_query_ms']}ms"
    )
    print(f"Top-{max(result['k_values'])} 미검색 문항: {result['failed_question_ids_at_max_k'] or '없음'}")
    print(f"상세 결과: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
