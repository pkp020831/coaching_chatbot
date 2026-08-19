#!/usr/bin/env python3
"""Gemini 평가 LLM으로 5단계 챗봇 답변을 채점한다."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from lesson_chatbot.llm_evaluation import (
    build_calibration_profile,
    build_evaluator_prompt,
    evaluate_answers,
    load_feedback,
    load_json_items,
    select_feedback_examples,
)


def parse_args() -> argparse.Namespace:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="5단계 서술형 답변을 교사 기준으로 평가합니다.")
    parser.add_argument("answers", type=Path, help="질문·생성 답변·검색 청크가 담긴 JSON 배열")
    parser.add_argument("--feedback", type=Path, default=Path("artifacts/stage5/teacher_feedback.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/stage5/llm_answer_eval.json"))
    parser.add_argument(
        "--model",
        default=os.environ.get("GEMINI_EVALUATOR_MODEL", "gemini-3.6-flash"),
        help="Gemini 평가 모델",
    )
    parser.add_argument("--example-limit", type=int, default=6, help="프롬프트에 넣을 교사 사례 수")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 입력과 첫 프롬프트만 검증")
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        items = load_json_items(args.answers)
        feedback = load_feedback(args.feedback)
        if args.dry_run:
            profile = build_calibration_profile(feedback)
            preview = {
                "status": "DRY_RUN_OK",
                "question_count": len(items),
                "calibration_profile": profile,
                "first_prompt": build_evaluator_prompt(
                    items[0], profile, select_feedback_examples(feedback, args.example_limit)
                ),
                "note": "API를 호출하지 않았으며 비용이 발생하지 않았습니다.",
            }
            write_json(args.output, preview)
            print(f"입력 {len(items)}개와 평가 프롬프트를 검증했습니다. API는 호출하지 않았습니다.")
            print(f"결과: {args.output.expanduser().resolve()}")
            return 0

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 없습니다. 먼저 --dry-run으로 검증할 수 있습니다.")
        try:
            from google import genai
        except ImportError as error:
            raise RuntimeError("google-genai가 없습니다: pip install -r requirements.txt") from error
        client = genai.Client(api_key=api_key)

        def call_gemini(prompt: str) -> str:
            response = client.models.generate_content(
                model=args.model,
                contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0},
            )
            if not response.text:
                raise RuntimeError("Gemini 평가 모델이 빈 응답을 반환했습니다.")
            return response.text

        result = evaluate_answers(
            items,
            call_gemini,
            feedback_records=feedback,
            example_limit=args.example_limit,
        )
        result["evaluator_model"] = args.model
        write_json(args.output, result)
        print(f"평가 문항: {result['question_count']}개")
        print(f"평균 점수: {result['summary']['mean_score']:.2f}, 통과율: {result['summary']['pass_rate']:.2%}")
        print(f"교사 피드백 반영: {result['calibration_profile']['feedback_count']}개")
        print(f"결과: {args.output.expanduser().resolve()}")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
