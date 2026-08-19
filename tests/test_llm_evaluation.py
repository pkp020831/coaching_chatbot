from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.llm_evaluation import (
    RUBRIC,
    append_feedback,
    build_calibration_profile,
    build_evaluator_prompt,
    evaluate_answers,
    load_feedback,
    validate_answer_item,
)


GOOD_SCORES = {name: 4 for name in RUBRIC}


class LLMEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.item = {
            "id": "S5Q01",
            "category": "개념 설명",
            "question": "열용량이 뭐야?",
            "answer": "열용량은 물체의 온도를 1℃ 높이는 데 필요한 열량입니다. [c1]",
            "expected_behavior": "direct",
            "retrieved_chunks": [{"chunk_id": "c1", "text": "열용량은 온도를 1℃ 높이는 데 필요한 열량이다."}],
        }

    def test_validation_rejects_unknown_behavior(self) -> None:
        invalid = {**self.item, "expected_behavior": "guess"}
        with self.assertRaisesRegex(ValueError, "expected_behavior"):
            validate_answer_item(invalid)

    def test_feedback_round_trip_and_bias_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feedback.jsonl"
            append_feedback(path, {
                "question_id": "S5Q01", "question": "질문", "answer": "답변",
                "expected_behavior": "direct", "teacher_scores": GOOD_SCORES,
                "evaluator_scores": {name: 3 for name in RUBRIC}, "teacher_notes": "더 후하게",
            })
            records = load_feedback(path)
            profile = build_calibration_profile(records)
            self.assertEqual(profile["feedback_count"], 1)
            self.assertTrue(all(offset == 1.0 for offset in profile["score_offsets"].values()))

    def test_evaluate_applies_calibration_and_checks_citation(self) -> None:
        feedback = [{
            "teacher_scores": GOOD_SCORES,
            "evaluator_scores": {name: 3 for name in RUBRIC},
            "question": "이전 질문", "answer": "이전 답", "expected_behavior": "direct",
        }]

        def fake_evaluator(prompt: str) -> dict:
            self.assertIn("수업 근거", prompt)
            return {
                "scores": {name: 3 for name in RUBRIC},
                "rationales": {}, "cited_chunk_ids": ["없는청크"],
                "strengths": [], "problems": [], "improvement": "인용 수정",
            }

        result = evaluate_answers([self.item], fake_evaluator, feedback_records=feedback)
        row = result["per_question"][0]
        self.assertEqual(row["calibrated_scores"]["class_grounding"], 4.0)
        self.assertEqual(row["calibrated_scores"]["citation_traceability"], 1.0)
        self.assertEqual(row["invalid_cited_chunk_ids"], ["없는청크"])

    def test_prompt_marks_gold_as_evaluation_only(self) -> None:
        item = validate_answer_item({**self.item, "gold_answer": "기준 답안"})
        profile = build_calibration_profile([])
        prompt = build_evaluator_prompt(item, profile, [])
        self.assertIn("gold_answer_for_evaluation_only", prompt)
        self.assertIn("검색이나 답변 생성에 사용됐다고 가정하지 않는다", prompt)

    def test_teacher_overall_scores_enable_shrunk_weight_learning(self) -> None:
        records = []
        for index in range(6):
            scores = {name: 3 for name in RUBRIC}
            scores["class_grounding"] = 1 + index * 0.8
            records.append({"teacher_scores": scores, "teacher_overall_score": 20 + index * 15})
        profile = build_calibration_profile(records)
        self.assertEqual(profile["weight_method"], "teacher_overall_correlation_shrunk_50pct")
        self.assertGreater(profile["weights"]["class_grounding"], RUBRIC["class_grounding"]["weight"])


if __name__ == "__main__":
    unittest.main()
