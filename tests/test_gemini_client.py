from __future__ import annotations

import json
import unittest

from lesson_chatbot.gemini_client import GeminiJSONClient


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class GeminiClientTest(unittest.TestCase):
    def test_structured_request_keeps_key_out_of_url(self) -> None:
        captured = {}

        def request_fn(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeHTTPResponse(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": '{"answer":"정답"}'}]},
                        }
                    ],
                    "usageMetadata": {"totalTokenCount": 12},
                    "modelVersion": "gemini-test-v1",
                }
            )

        client = GeminiJSONClient(
            "secret-test-key",
            model="gemini-test",
            request_fn=request_fn,
            sleep_fn=lambda _: None,
        )
        result = client.generate_json(
            system_instruction="규칙",
            prompt="질문",
            response_schema={"type": "object"},
        )
        request = captured["request"]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result.data, {"answer": "정답"})
        self.assertNotIn("secret-test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "secret-test-key")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", body["generationConfig"])


if __name__ == "__main__":
    unittest.main()
