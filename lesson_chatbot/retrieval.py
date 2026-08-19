"""4단계: SQLite FTS5의 BM25로 화학 수업 청크를 검색한다."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

from .database import connect_database


INDEX_STATE_KEY = "bm25_fts_fingerprint_v1"
TOKEN_RE = re.compile(r"[A-Za-z]+[A-Za-z0-9]*|\d+(?:\.\d+)?|[가-힣]+")
PARTICLE_SUFFIXES = (
    "으로부터",
    "에게서",
    "이랑",
    "이라면",
    "이라고",
    "이라는",
    "입니다",
    "인가요",
    "이에요",
    "예요",
    "에서는",
    "에게",
    "한테",
    "부터",
    "까지",
    "보다",
    "처럼",
    "만큼",
    "으로",
    "에서",
    "에는",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "와",
    "과",
    "도",
    "만",
    "에",
    "로",
    "요",
)
STOPWORDS = {"그", "이", "저", "것", "거", "수", "좀", "네", "예", "응", "음", "어", "자"}

FTS_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    lesson_id UNINDEXED,
    exact_terms,
    ngram_terms,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    for source, target in (
        ("열 에너지", "열에너지"),
        ("열 용량", "열용량"),
        ("가열 곡선", "가열곡선"),
        ("상태 변화", "상태변화"),
        ("입자 모형", "입자모형"),
    ):
        normalized = normalized.replace(source, target)
    return normalized


def _variants(token: str) -> set[str]:
    variants = {token}
    if not re.fullmatch(r"[가-힣]+", token):
        return variants
    for suffix in PARTICLE_SUFFIXES:
        if token.endswith(suffix):
            root = token[: -len(suffix)]
            if len(root) >= 2:
                variants.add(root)
            break
    return variants


def make_search_terms(text: str) -> tuple[list[str], list[str]]:
    """조사 제거 어절과 한글 2·3-gram을 만든다.

    FTS5 기본 토크나이저는 한국어 조사를 분리하지 않으므로, 예를 들어
    ``열용량이``와 ``열용량``이 같은 검색어로 이어지도록 보조 토큰을 저장한다.
    """
    exact_terms: set[str] = set()
    ngram_terms: set[str] = set()
    for token in TOKEN_RE.findall(_normalize(text)):
        if token in STOPWORDS:
            continue
        for variant in _variants(token):
            exact_terms.add(f"w{variant}")
            if re.fullmatch(r"[가-힣]+", variant):
                for width, prefix in ((2, "b"), (3, "t")):
                    if len(variant) >= width:
                        ngram_terms.update(
                            f"{prefix}{variant[index:index + width]}"
                            for index in range(len(variant) - width + 1)
                        )
    return sorted(exact_terms), sorted(ngram_terms)


def _fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in connection.execute("SELECT chunk_id, content_sha256 FROM chunks ORDER BY chunk_id"):
        digest.update(f"{row['chunk_id']}:{row['content_sha256']}\n".encode("utf-8"))
    return digest.hexdigest()


def ensure_bm25_index(database_path: Path) -> dict[str, Any]:
    """청크가 달라졌을 때만 FTS5 인덱스를 다시 만든다."""
    started = time.perf_counter()
    database_path = database_path.expanduser().resolve()
    with connect_database(database_path) as connection:
        try:
            connection.executescript(FTS_SCHEMA_SQL)
        except sqlite3.OperationalError as error:
            raise RuntimeError("현재 Python의 SQLite가 FTS5를 지원하지 않습니다.") from error

        fingerprint = _fingerprint(connection)
        state = connection.execute(
            "SELECT value FROM schema_info WHERE key = ?", (INDEX_STATE_KEY,)
        ).fetchone()
        indexed_count = connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        chunk_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        rebuilt = state is None or state["value"] != fingerprint or indexed_count != chunk_count
        if rebuilt:
            connection.execute("DELETE FROM chunks_fts")
            rows = connection.execute("SELECT chunk_id, lesson_id, text FROM chunks ORDER BY chunk_id").fetchall()
            connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, lesson_id, exact_terms, ngram_terms) VALUES(?, ?, ?, ?)",
                (
                    (
                        row["chunk_id"],
                        row["lesson_id"],
                        " ".join(make_search_terms(row["text"])[0]),
                        " ".join(make_search_terms(row["text"])[1]),
                    )
                    for row in rows
                ),
            )
            connection.execute(
                "INSERT INTO schema_info(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (INDEX_STATE_KEY, fingerprint),
            )

    return {
        "rebuilt": rebuilt,
        "indexed_chunk_count": chunk_count,
        "index_build_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _quote_fts_token(token: str) -> str:
    return f'"{token.replace("\"", "")}"'


def build_fts_query(query: str) -> str:
    exact_terms, ngram_terms = make_search_terms(query)
    clauses: list[str] = []
    if exact_terms:
        clauses.append("exact_terms : (" + " OR ".join(_quote_fts_token(term) for term in exact_terms) + ")")
    if ngram_terms:
        clauses.append("ngram_terms : (" + " OR ".join(_quote_fts_token(term) for term in ngram_terms) + ")")
    if not clauses:
        raise ValueError("검색할 핵심 단어를 입력해 주세요.")
    return " OR ".join(clauses)


def search_bm25(
    database_path: Path,
    query: str,
    *,
    top_k: int = 5,
    lesson_id: str | None = None,
    topic: str | None = None,
    question_number: int | None = None,
) -> dict[str, Any]:
    """상위 k개 청크를 BM25 점수 내림차순으로 반환한다."""
    if not query.strip():
        raise ValueError("검색어가 비어 있습니다.")
    if not 1 <= top_k <= 50:
        raise ValueError("top_k는 1~50 사이여야 합니다.")
    index_metrics = ensure_bm25_index(database_path)
    fts_query = build_fts_query(query)
    conditions = ["chunks_fts MATCH ?"]
    parameters: list[Any] = [fts_query]
    if lesson_id:
        conditions.append("c.lesson_id = ?")
        parameters.append(lesson_id)
    if topic:
        conditions.append(
            "EXISTS (SELECT 1 FROM chunk_topics ct WHERE ct.chunk_id = c.chunk_id AND ct.topic = ?)"
        )
        parameters.append(topic)
    if question_number is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM chunk_question_numbers cq "
            "WHERE cq.chunk_id = c.chunk_id AND cq.question_number = ?)"
        )
        parameters.append(question_number)
    where_sql = " AND ".join(conditions)
    database_path = database_path.expanduser().resolve()
    started = time.perf_counter()
    with connect_database(database_path) as connection:
        candidate_count = connection.execute(
            f"SELECT COUNT(*) FROM chunks_fts JOIN chunks c USING(chunk_id) WHERE {where_sql}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT
                c.chunk_id, c.lesson_id, l.title, l.lesson_date, c.chunk_index,
                c.source_line_start, c.source_line_end, c.start_sec, c.end_sec,
                c.speakers_json, c.topics_json, c.question_numbers_json, c.text,
                -bm25(chunks_fts, 0.0, 0.0, 5.0, 1.0) AS score
            FROM chunks_fts
            JOIN chunks c USING(chunk_id)
            JOIN lessons l ON l.lesson_id = c.lesson_id
            WHERE {where_sql}
            ORDER BY bm25(chunks_fts, 0.0, 0.0, 5.0, 1.0), c.chunk_index
            LIMIT ?
            """,
            [*parameters, top_k],
        ).fetchall()

    results = [
        {
            "rank": index,
            "chunk_id": row["chunk_id"],
            "lesson_id": row["lesson_id"],
            "title": row["title"],
            "lesson_date": row["lesson_date"],
            "chunk_index": row["chunk_index"],
            "score": round(row["score"], 6),
            "source_line_start": row["source_line_start"],
            "source_line_end": row["source_line_end"],
            "start_sec": row["start_sec"],
            "end_sec": row["end_sec"],
            "speakers": json.loads(row["speakers_json"]),
            "topics": json.loads(row["topics_json"]),
            "question_numbers": json.loads(row["question_numbers_json"]),
            "text": row["text"],
        }
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "query": query,
        "top_k_requested": top_k,
        "candidate_count": candidate_count,
        "returned_count": len(results),
        "query_latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "index": index_metrics,
        "results": results,
    }
