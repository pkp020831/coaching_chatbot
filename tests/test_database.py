from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.database import connect_database, ingest_stage2_artifact, validate_lesson


class DatabaseTest(unittest.TestCase):
    def make_artifact(self, directory: str) -> Path:
        payload = {
            "stage": 2,
            "source_file": "2026-08-19-chemistry.md",
            "source_metadata": {
                "title": "열에너지 수업",
                "date": "2026-08-19",
                "language": "ko-KR",
            },
            "chunking_config": {"target_chars": 700, "overlap_turns": 1},
            "chunks": [
                {
                    "chunk_index": 0,
                    "turn_start": 0,
                    "turn_end": 1,
                    "source_line_start": 1,
                    "source_line_end": 2,
                    "start_sec": 0.0,
                    "end_sec": 10.0,
                    "speakers": ["선생님", "학생"],
                    "char_count": 37,
                    "text": "선생님: 113번에서 상태 변화와 열에너지 흡수를 설명합니다.\n학생: 네.",
                },
                {
                    "chunk_index": 1,
                    "turn_start": 1,
                    "turn_end": 2,
                    "source_line_start": 2,
                    "source_line_end": 3,
                    "start_sec": 8.0,
                    "end_sec": 20.0,
                    "speakers": ["학생", "선생님"],
                    "char_count": 34,
                    "text": "학생: 열용량은 무슨 뜻인가요?\n선생님: 물질의 온도와 관련된 개념입니다.",
                },
            ],
        }
        artifact = Path(directory) / "lesson.chunks.json"
        artifact.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return artifact

    def test_ingest_metadata_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.make_artifact(directory)
            database = Path(directory) / "lessons.sqlite3"
            ingestion = ingest_stage2_artifact(artifact, database)
            result = validate_lesson(database, ingestion["lesson_id"], ingestion["enriched_chunks"])
            with connect_database(database) as connection:
                topic_count = connection.execute(
                    "SELECT COUNT(*) FROM chunk_topics WHERE topic = '상태 변화·열에너지'"
                ).fetchone()[0]
                question_count = connection.execute(
                    "SELECT COUNT(*) FROM chunk_question_numbers WHERE question_number = 113"
                ).fetchone()[0]

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(topic_count, 1)
        self.assertEqual(question_count, 1)

    def test_reingest_replaces_instead_of_duplicating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = self.make_artifact(directory)
            database = Path(directory) / "lessons.sqlite3"
            first = ingest_stage2_artifact(artifact, database)
            second = ingest_stage2_artifact(artifact, database)
            with connect_database(database) as connection:
                lesson_count = connection.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
                chunk_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

        self.assertEqual(first["previous_chunk_count_replaced"], 0)
        self.assertEqual(second["previous_chunk_count_replaced"], 2)
        self.assertEqual(lesson_count, 1)
        self.assertEqual(chunk_count, 2)

    def test_connection_is_closed_after_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "lessons.sqlite3"
            with connect_database(database) as connection:
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            database.unlink()
            self.assertFalse(database.exists())

    def test_transaction_rolls_back_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "lessons.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with connect_database(database) as connection:
                    connection.execute(
                        "INSERT INTO schema_info(key, value) VALUES('rollback-test', 'pending')"
                    )
                    raise RuntimeError("rollback")

            with connect_database(database) as connection:
                stored = connection.execute(
                    "SELECT value FROM schema_info WHERE key = 'rollback-test'"
                ).fetchone()
            self.assertIsNone(stored)


if __name__ == "__main__":
    unittest.main()
