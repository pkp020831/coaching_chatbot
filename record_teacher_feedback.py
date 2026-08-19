#!/usr/bin/env python3
"""평가 LLM 결과에 대한 교사의 실제 채점을 JSONL로 누적한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lesson_chatbot.llm_evaluation import RUBRIC, append_feedback, build_calibration_profile, load_feedback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="교사 채점을 기록해 이후 평가 LLM을 보정합니다.")
    parser.add_argument("evaluation", type=Path, help="evaluate_llm_answers.py가 만든 결과 JSON")
    parser.add_argument("question_id", help="채점할 문항 ID")
    parser.add_argument(
        "--score", action="append", required=True, metavar="항목=1~5",
        help="평가 항목별 교사 점수. 여섯 항목을 각각 한 번씩 입력",
    )
    parser.add_argument("--overall-score", type=float, help="선택: 교사의 종합 점수(0~100)")
    pass_group = parser.add_mutually_exclusive_group()
    pass_group.add_argument("--pass", dest="teacher_pass", action="store_true")
    pass_group.add_argument("--fail", dest="teacher_pass", action="store_false")
    parser.set_defaults(teacher_pass=None)
    parser.add_argument("--notes", default="", help="평가 이유·개선 의견")
    parser.add_argument("--feedback", type=Path, default=Path("artifacts/stage5/teacher_feedback.jsonl"))
    return parser.parse_args()


def parse_scores(values: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"점수 형식은 항목=점수입니다: {value}")
        name, raw_score = value.split("=", 1)
        name = name.strip()
        if name not in RUBRIC:
            raise ValueError(f"알 수 없는 평가 항목: {name}; 허용값={list(RUBRIC)}")
        if name in result:
            raise ValueError(f"평가 항목이 중복되었습니다: {name}")
        result[name] = float(raw_score)
    missing = set(RUBRIC) - set(result)
    if missing:
        raise ValueError(f"교사 점수가 누락되었습니다: {sorted(missing)}")
    return result


def main() -> int:
    args = parse_args()
    try:
        payload = json.loads(args.evaluation.expanduser().resolve().read_text(encoding="utf-8-sig"))
        questions = payload.get("per_question", [])
        item = next((row for row in questions if str(row.get("id")) == args.question_id), None)
        if item is None:
            raise ValueError(f"평가 결과에서 문항을 찾을 수 없습니다: {args.question_id}")
        teacher_scores = parse_scores(args.score)
        record = {
            "question_id": item["id"],
            "category": item.get("category", "미분류"),
            "question": item["question"],
            "answer": item["answer"],
            "expected_behavior": item.get("expected_behavior"),
            "teacher_scores": teacher_scores,
            "teacher_overall_score": args.overall_score,
            "teacher_notes": args.notes,
            "evaluator_scores": item.get("evaluator_raw_scores"),
        }
        if args.teacher_pass is not None:
            record["teacher_pass"] = args.teacher_pass
        saved = append_feedback(args.feedback, record)
        profile = build_calibration_profile(load_feedback(args.feedback))
        print(f"교사 피드백 저장: {saved['feedback_id']}")
        print(f"누적 피드백: {profile['feedback_count']}개, LLM-교사 점수 쌍: {profile['paired_score_count']}개")
        print(f"현재 점수 보정값: {profile['score_offsets']}")
        print("이 보정은 모델 파인튜닝이 아니라 사례·통계 기반 보정입니다.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
