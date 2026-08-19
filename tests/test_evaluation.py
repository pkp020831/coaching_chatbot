from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.database import ingest_stage2_artifact
from lesson_chatbot.evaluation import evaluate_bm25, load_evaluation_dataset


class EvaluationTest(unittest.TestCase):
    def make_files(self, directory: str) -> tuple[Path, Path, str]:
        artifact = Path(directory) / "lesson.chunks.json"
        artifact.write_text(
            json.dumps(
                {
                    "stage": 2,
                    "source_file": "chemistry.md",
                    "source_metadata": {"title": "화학", "date": "2026-08-19", "language": "ko"},
                    "chunking_config": {"target_chars": 700, "overlap_turns": 1},
                    "chunks": [
                        {
                            "chunk_index": 0,
                            "turn_start": 0,
                            "turn_end": 0,
                            "source_line_start": 1,
                            "source_line_end": 1,
                            "start_sec": None,
                            "end_sec": None,
                            "speakers": ["선생님"],
                            "text": "선생님: 열용량은 온도를 1℃ 높이는 데 필요한 열량입니다.",
                        },
                        {
                            "chunk_index": 1,
                            "turn_start": 1,
                            "turn_end": 1,
                            "source_line_start": 2,
                            "source_line_end": 2,
                            "start_sec": None,
                            "end_sec": None,
                            "speakers": ["선생님"],
                            "text": "선생님: 끓는점에서는 온도가 일정합니다.",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        database = Path(directory) / "lessons.sqlite3"
        ingestion = ingest_stage2_artifact(artifact, database)
        relevant_id = ingestion["enriched_chunks"][0]["chunk_id"]
        dataset = Path(directory) / "eval.json"
        dataset.write_text(
            json.dumps(
                [
                    {
                        "id": "Q01",
                        "category": "개념 설명",
                        "question": "열용량이 뭐야?",
                        "relevant_chunk_ids": [relevant_id],
                        "target_keywords": ["열용량", "열량"],
                        "gold_answer": "온도를 1℃ 높이는 데 필요한 열량입니다.",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return database, dataset, relevant_id

    def test_evaluation_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, dataset, _ = self.make_files(directory)
            result = evaluate_bm25(database, dataset, k_values=(1, 2))

        self.assertEqual(result["summary"]["@1"]["hit"], 1.0)
        self.assertEqual(result["summary"]["@1"]["mrr"], 1.0)
        self.assertEqual(result["tokenizer_validation"]["tokenization_rate"], 1.0)

    def test_unknown_relevant_chunk_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, dataset, _ = self.make_files(directory)
            payload = json.loads(dataset.read_text(encoding="utf-8"))
            payload[0]["relevant_chunk_ids"] = ["chunk_missing"]
            dataset.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "DB에 없는"):
                load_evaluation_dataset(dataset, database)


if __name__ == "__main__":
    unittest.main()
