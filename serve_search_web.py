#!/usr/bin/env python3
"""로컬 웹 UI가 사용할 BM25 검색 API를 제공한다."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lesson_chatbot.answering import answer_question, create_gemini_client_from_env
from lesson_chatbot.gemini_client import GeminiAPIError
from lesson_chatbot.retrieval import search_bm25


class SearchAPIHandler(BaseHTTPRequestHandler):
    database_path = Path("data/lessons.sqlite3")
    answer_client = None

    def _allowed_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        if origin in {"http://localhost:3000", "http://127.0.0.1:3000"}:
            return origin
        return "http://localhost:3000"

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._allowed_origin())
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(HTTPStatus.NO_CONTENT, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "database": self.database_path.name,
                    "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
                },
            )
            return
        if parsed.path != "/api/search":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "지원하지 않는 경로입니다."})
            return

        parameters = parse_qs(parsed.query)
        query = parameters.get("q", [""])[0].strip()
        try:
            top_k = int(parameters.get("k", ["5"])[0])
            result = search_bm25(self.database_path, query, top_k=top_k)
        except (ValueError, sqlite3.Error, RuntimeError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._send_json(HTTPStatus.OK, result)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/answer":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "지원하지 않는 경로입니다."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > 16_384:
                raise ValueError("요청 본문 크기가 올바르지 않습니다.")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("요청 본문은 JSON 객체여야 합니다.")
            question = str(payload.get("question", "")).strip()
            top_k = int(payload.get("top_k", 5))
            if self.__class__.answer_client is None:
                self.__class__.answer_client = create_gemini_client_from_env()
            result = answer_question(
                self.database_path,
                question,
                client=self.__class__.answer_client,
                top_k=top_k,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except GeminiAPIError as error:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return
        except (sqlite3.Error, OSError, RuntimeError) as error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})
            return
        self._send_json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[검색 API] {self.address_string()} - {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BM25 검색 로컬 API 서버")
    parser.add_argument("--host", default="127.0.0.1", help="바인딩 주소")
    parser.add_argument("--port", type=int, default=8765, help="포트 (기본값: 8765)")
    parser.add_argument(
        "--database", type=Path, default=Path("data/lessons.sqlite3"), help="SQLite DB 경로"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        raise SystemExit(f"DB를 찾을 수 없습니다: {database_path}")
    SearchAPIHandler.database_path = database_path
    server = ThreadingHTTPServer((args.host, args.port), SearchAPIHandler)
    print(f"BM25 검색 API: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
