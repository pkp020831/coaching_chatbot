#!/usr/bin/env python3
"""5단계 질문 세트에 대한 답변을 생성해 별도 평가 LLM 입력을 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.answering import answer_question, create_gemini_client_from_env
from lesson_chatbot.gemini_client import GeminiAPIError


MODE_TO_BEHAVIOR = {
    "DIRECT_LESSON": "direct",
    "INFERRED_LESSON": "inferred",
    "RELATED_SUPPLEMENT": "related_general",
    "SAFE_REFUSAL": "out_of_scope",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="5단계 평가 질문의 Gemini 답변 생성")
    parser.add_argument("dataset", type=Path, nargs="?", default=Path("stage5_eval_dataset.json"))
    parser.add_argument("--database", type=Path, default=Path("data/lessons.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage5/generated_answers.json"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, help="비용 확인용 앞 N문항만 실행")
    return parser.parse_args()


def load_dataset(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("5단계 데이터셋에 비어 있지 않은 items 배열이 필요합니다.")
    return items


def main() -> int:
    args = parse_args()
    try:
        items = load_dataset(args.dataset)
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("--limit은 1 이상이어야 합니다.")
            items = items[: args.limit]
        client = create_gemini_client_from_env()
        results: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            answer = answer_question(
                args.database,
                str(item["question"]),
                client=client,
                top_k=args.top_k,
            )
            # gold_answer와 채점 기준은 생성 후 평가 레코드에만 결합한다.
            # answer_question에는 question 외의 데이터셋 필드를 전달하지 않는다.
            results.append(
                {
                    "id": item["id"],
                    "category": item.get("category", "미분류"),
                    "question": item["question"],
                    "answer": answer["answer"],
                    "answer_scope": answer["scope"],
                    "cited_chunk_ids": answer["cited_chunk_ids"],
                    "retrieved_chunks": [
                        {"chunk_id": row["chunk_id"], "text": row["text"]}
                        for row in answer["retrieved_chunks"]
                    ],
                    "expected_behavior": MODE_TO_BEHAVIOR[item["answer_mode"]],
                    "required_points": item.get("required_points", []),
                    "forbidden_claims": item.get("forbidden_claims", []),
                    "grading_focus": item.get("grading_focus", []),
                    "gold_answer": item.get("gold_answer"),
                    "generation": answer["generation"],
                    "retrieval": answer["retrieval"],
                }
            )
            print(f"[{index}/{len(items)}] {item['id']} 답변 생성 완료")
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"평가 LLM 입력: {output}")
        return 0
    except (KeyError, OSError, ValueError, RuntimeError, GeminiAPIError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
