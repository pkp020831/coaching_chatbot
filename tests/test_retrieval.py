from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.database import ingest_stage2_artifact
from lesson_chatbot.retrieval import ensure_bm25_index, search_bm25


class RetrievalTest(unittest.TestCase):
    def make_database(self, directory: str) -> Path:
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
                            "text": "선생님: 열용량은 물질의 온도를 1℃ 높이는 데 필요한 열량입니다.",
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
                            "text": "선생님: 113번에서 융해는 열에너지를 흡수하는 상태 변화라고 설명했습니다.",
                        },
                        {
                            "chunk_index": 2,
                            "turn_start": 2,
                            "turn_end": 2,
                            "source_line_start": 3,
                            "source_line_end": 3,
                            "start_sec": None,
                            "end_sec": None,
                            "speakers": ["선생님"],
                            "text": "선생님: 끓는점에서는 온도가 일정해집니다.",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        database = Path(directory) / "lessons.sqlite3"
        ingest_stage2_artifact(artifact, database)
        return database

    def test_bm25_returns_relevant_chunk_for_particle_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            result = search_bm25(database, "열용량이 무엇인가요?", top_k=2)

        self.assertGreaterEqual(result["returned_count"], 1)
        self.assertLessEqual(result["returned_count"], 2)
        self.assertIn("열용량은", result["results"][0]["text"])
        self.assertGreater(result["results"][0]["score"], 0)

    def test_question_number_filter_and_index_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            first = ensure_bm25_index(database)
            second = ensure_bm25_index(database)
            result = search_bm25(database, "상태 변화", top_k=5, question_number=113)

        self.assertTrue(first["rebuilt"] or first["indexed_chunk_count"] == 3)
        self.assertFalse(second["rebuilt"])
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["results"][0]["question_numbers"], [113])

    def test_returns_only_top_k_in_rank_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            result = search_bm25(database, "선생님", top_k=2)

        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual([item["rank"] for item in result["results"]], [1, 2])
        self.assertGreaterEqual(result["results"][0]["score"], result["results"][1]["score"])


if __name__ == "__main__":
    unittest.main()
