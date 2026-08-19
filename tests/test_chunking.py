from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lesson_chatbot.chunking import build_chunks, load_transcript
from run_chunking import evaluate


class ChunkingTest(unittest.TestCase):
    def test_markdown_parsing_and_chunk_coverage(self) -> None:
        content = """---
title: "화학 수업"
date: "2026-08-19"
language: "ko-KR"
---

# 전사본

**선생님:** 물질을 가열하면 입자의 운동이 활발해집니다. 열에너지를 흡수합니다.

**학생:** 고체에서 액체로 변하는 것도 같은 방향인가요?

**선생님:** 네. 융해는 열에너지를 흡수하는 상태 변화입니다.
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lesson.md"
            path.write_text(content, encoding="utf-8")
            transcript = load_transcript(path)
            chunks, metrics = build_chunks(transcript, target_chars=200, overlap_turns=1)

        self.assertEqual(len(transcript.turns), 3)
        self.assertEqual(transcript.metadata["title"], "화학 수업")
        self.assertTrue(chunks)
        self.assertTrue(all(chunk["char_count"] <= 200 for chunk in chunks))
        self.assertEqual(metrics["line_parse_rate"], 1.0)
        self.assertEqual(metrics["source_turn_coverage_rate"], 1.0)
        self.assertEqual(metrics["empty_chunk_rate"], 0.0)
        self.assertEqual(evaluate(metrics)["status"], "PASS")

    def test_long_turn_is_split_under_target(self) -> None:
        sentence = "비열은 물질 일 그램의 온도를 일 도 높이는 데 필요한 열량입니다. "
        content = f"**선생님:** {sentence * 20}\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.md"
            path.write_text(content, encoding="utf-8")
            transcript = load_transcript(path)
            chunks, metrics = build_chunks(transcript, target_chars=200, overlap_turns=0)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(metrics["oversize_chunk_rate"], 0.0)
        self.assertEqual(metrics["source_turn_coverage_rate"], 1.0)

    def test_transcription_json_is_supported(self) -> None:
        payload = {
            "transcription": {"detected_language": "ko"},
            "segments": [
                {"speaker": "화자 1", "start_sec": 0, "end_sec": 4, "text": "열용량을 설명합니다."},
                {"speaker": "화자 2", "start_sec": 4, "end_sec": 7, "text": "질문이 있습니다."},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lesson.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            transcript = load_transcript(path)
            chunks, metrics = build_chunks(transcript, target_chars=200)

        self.assertEqual(len(transcript.turns), 2)
        self.assertEqual(chunks[0]["start_sec"], 0.0)
        self.assertEqual(metrics["segment_parse_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
