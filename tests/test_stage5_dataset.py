import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage5EvaluationDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        private_dataset = ROOT / "stage5_eval_dataset.json"
        example_dataset = ROOT / "examples/stage5_eval_dataset.example.json"
        cls.using_private_dataset = private_dataset.is_file()
        cls.dataset = json.loads(
            (private_dataset if cls.using_private_dataset else example_dataset).read_text(encoding="utf-8")
        )
        if cls.using_private_dataset:
            chunk_document = json.loads(
                (ROOT / "artifacts/stage2/audio_transcript_science_class.chunks.json").read_text(
                    encoding="utf-8"
                )
            )
            cls.valid_chunk_ids = {
                f"2026-08-19_audio_transcript_science_class:chunk:{chunk['chunk_index']:04d}"
                for chunk in chunk_document["chunks"]
            }
        else:
            cls.valid_chunk_ids = {
                chunk_id
                for item in cls.dataset["items"]
                for chunk_id in item["relevant_chunk_ids"]
            }

    def test_balanced_coverage_and_unique_ids(self) -> None:
        items = self.dataset["items"]
        self.assertEqual(len(items), 30 if self.using_private_dataset else 5)
        self.assertEqual(len({item["id"] for item in items}), len(items))
        self.assertEqual(
            Counter(item["category"] for item in items),
            {category: 6 if self.using_private_dataset else 1 for category in (
                "직접 수업 운영", "직접 개념", "간접 추론 가능",
                "관련 일반화학 보충", "수업 밖 안전 거절",
            )},
        )

    def test_required_fields_and_evidence_policy(self) -> None:
        required_fields = {
            "id",
            "category",
            "answer_mode",
            "question",
            "relevant_chunk_ids",
            "target_keywords",
            "expected_behavior",
            "required_points",
            "forbidden_claims",
            "grading_focus",
            "gold_answer",
        }
        for item in self.dataset["items"]:
            self.assertTrue(required_fields.issubset(item), item["id"])
            self.assertTrue(item["question"].strip(), item["id"])
            self.assertTrue(item["gold_answer"].strip(), item["id"])
            self.assertTrue(item["required_points"], item["id"])
            self.assertTrue(item["forbidden_claims"], item["id"])

            if item["answer_mode"] == "SAFE_REFUSAL":
                self.assertEqual(item["relevant_chunk_ids"], [], item["id"])
            else:
                self.assertTrue(item["relevant_chunk_ids"], item["id"])
                self.assertTrue(
                    set(item["relevant_chunk_ids"]).issubset(self.valid_chunk_ids),
                    item["id"],
                )

    def test_gold_answer_is_explicitly_answer_evaluation_only(self) -> None:
        policy = self.dataset["usage_policy"]
        restriction = policy["gold_answer_restriction"]
        self.assertIn("5단계", restriction)
        self.assertIn("검색", restriction)
        self.assertIn("사용하지", restriction)

    def test_public_example_is_safe_and_complete(self) -> None:
        example = json.loads(
            (ROOT / "examples/stage5_eval_dataset.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(example["items"]), 5)
        self.assertEqual(
            {item["answer_mode"] for item in example["items"]},
            {"DIRECT_LESSON", "INFERRED_LESSON", "RELATED_SUPPLEMENT", "SAFE_REFUSAL"},
        )
        self.assertTrue(all(item["gold_answer"] for item in example["items"]))
        self.assertNotIn("우진", json.dumps(example, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
