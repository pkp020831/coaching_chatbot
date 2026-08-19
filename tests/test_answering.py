from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.answering import answer_question
from lesson_chatbot.database import connect_database
from lesson_chatbot.gemini_client import GeminiJSONResponse


class FakeClient:
    model = "fake-gemini"

    def __init__(self, data: dict) -> None:
        self.data = data
        self.last_prompt = ""

    def generate_json(self, **kwargs) -> GeminiJSONResponse:
        self.last_prompt = kwargs["prompt"]
        return GeminiJSONResponse(self.data, {"totalTokenCount": 10}, "fake-v1", 1.5)


def make_database(path: Path) -> str:
    lesson_id = "lesson-chemistry"
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO lessons VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lesson_id,
                "화학 수업",
                "2026-08-19",
                "화학",
                "ko",
                "lesson.md",
                "hash",
                "{}",
                "{}",
                "2026-08-19T00:00:00Z",
                "2026-08-19T00:00:00Z",
            ),
        )
        text = "선생님: 열용량은 물질의 온도를 1℃ 높이는 데 필요한 열량입니다."
        connection.execute(
            "INSERT INTO chunks VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{lesson_id}:chunk:0000",
                lesson_id,
                0,
                0,
                0,
                1,
                1,
                None,
                None,
                json.dumps(["선생님"]),
                json.dumps(["열용량·비열"]),
                json.dumps(["개념 설명"]),
                json.dumps(["열용량"]),
                "[]",
                len(text),
                "content-hash",
                text,
            ),
        )
        connection.execute(
            "INSERT INTO chunk_topics VALUES(?, ?)",
            (f"{lesson_id}:chunk:0000", "열용량·비열"),
        )
        connection.execute(
            "INSERT INTO chunk_chemistry_terms VALUES(?, ?)",
            (f"{lesson_id}:chunk:0000", "열용량"),
        )
    return f"{lesson_id}:chunk:0000"


class AnsweringTest(unittest.TestCase):
    def test_direct_answer_keeps_only_valid_citations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            chunk_id = make_database(database)
            client = FakeClient(
                {
                    "scope": "DIRECT_CLASS",
                    "answer": "열용량은 온도를 1℃ 높이는 데 필요한 열량입니다.",
                    "evidence_note": "수업에서 직접 정의함",
                    "cited_chunk_ids": [chunk_id, "invented:chunk"],
                    "used_general_knowledge": False,
                    "confidence": "HIGH",
                }
            )
            result = answer_question(database, "열용량이 뭐야?", client=client, top_k=1)
            self.assertEqual(result["scope"], "DIRECT_CLASS")
            self.assertEqual(result["cited_chunk_ids"], [chunk_id])
            self.assertEqual(len(result["evidence"]), 1)
            self.assertIn("BM25 검색 근거", client.last_prompt)

    def test_missing_course_info_is_replaced_with_safe_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            make_database(database)
            client = FakeClient(
                {
                    "scope": "COURSE_INFO_MISSING",
                    "answer": "아마 휴강일 거예요.",
                    "evidence_note": "근거 없음",
                    "cited_chunk_ids": [],
                    "used_general_knowledge": False,
                    "confidence": "LOW",
                }
            )
            result = answer_question(database, "다음 주 휴강이야?", client=client)
            self.assertIn("추측하지 않고", result["answer"])
            self.assertNotIn("아마 휴강", result["answer"])
            self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
