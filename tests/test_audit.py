from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.audit import audit_bm25_hits
from lesson_chatbot.database import ingest_stage2_artifact


class AuditTest(unittest.TestCase):
    def test_clear_lexical_hit_is_not_classified_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "lesson.chunks.json"
            artifact.write_text(
                json.dumps(
                    {
                        "stage": 2,
                        "source_file": "chemistry.md",
                        "source_metadata": {"title": "화학", "date": "2026-08-19"},
                        "chunking_config": {},
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
                                "text": "열용량은 온도를 1℃ 높이는 데 필요한 열량입니다.",
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
                                "text": "끓는점에서는 온도가 일정합니다.",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            database = Path(directory) / "lessons.sqlite3"
            ingestion = ingest_stage2_artifact(artifact, database)
            dataset = Path(directory) / "eval.json"
            dataset.write_text(
                json.dumps(
                    [
                        {
                            "id": "Q01",
                            "category": "개념 설명",
                            "question": "열용량의 정확한 정의는 무엇인가요?",
                            "relevant_chunk_ids": [ingestion["enriched_chunks"][0]["chunk_id"]],
                            "target_keywords": ["열용량", "열량"],
                            "gold_answer": "온도를 1℃ 높이는 데 필요한 열량입니다.",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = audit_bm25_hits(database, dataset, top_k=1)

        item = result["per_question"][0]
        self.assertTrue(item["hit_at_k"])
        self.assertNotEqual(item["classification"], "실패")
        self.assertIn("열용량", item["distinctive_exact_matches"])
        self.assertFalse(result["summary"]["target_or_gold_used_for_retrieval"])


if __name__ == "__main__":
    unittest.main()
