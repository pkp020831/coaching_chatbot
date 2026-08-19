"""3단계: 청크에 화학 수업 메타데이터를 붙여 SQLite에 저장한다."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1"
QUESTION_NUMBER_RE = re.compile(r"(?<!\d)(\d{2,4})\s*번")

TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "열용량·비열": ("열용량", "비열", "열량", "칼로리"),
    "상태 변화·열에너지": (
        "상태 변화",
        "열에너지",
        "열 에너지",
        "흡수",
        "방출",
        "고체",
        "액체",
        "기체",
    ),
    "가열 곡선·끓는점": ("가열 곡선", "가열곡선", "가열 시간", "끓는점"),
    "입자 모형": ("입자 모형", "입자의 운동"),
    "숙제·퀴즈 피드백": ("숙제", "퀴즈", "정답률", "실수"),
}

CHEMISTRY_TERMS = (
    "열용량",
    "비열",
    "열량",
    "열에너지",
    "상태 변화",
    "고체",
    "액체",
    "기체",
    "융해",
    "응고",
    "기화",
    "액화",
    "승화",
    "끓는점",
    "가열 곡선",
    "입자 모형",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    lesson_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    lesson_date TEXT,
    subject TEXT NOT NULL,
    language TEXT NOT NULL,
    source_file TEXT NOT NULL,
    stage2_artifact_sha256 TEXT NOT NULL,
    source_metadata_json TEXT NOT NULL,
    chunking_config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    lesson_id TEXT NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    turn_start INTEGER,
    turn_end INTEGER,
    source_line_start INTEGER,
    source_line_end INTEGER,
    start_sec REAL,
    end_sec REAL,
    speakers_json TEXT NOT NULL,
    topics_json TEXT NOT NULL,
    content_types_json TEXT NOT NULL,
    chemistry_terms_json TEXT NOT NULL,
    question_numbers_json TEXT NOT NULL,
    char_count INTEGER NOT NULL CHECK(char_count > 0),
    content_sha256 TEXT NOT NULL,
    text TEXT NOT NULL CHECK(length(text) > 0),
    UNIQUE(lesson_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS chunk_topics (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    PRIMARY KEY(chunk_id, topic)
);

CREATE TABLE IF NOT EXISTS chunk_chemistry_terms (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    PRIMARY KEY(chunk_id, term)
);

CREATE TABLE IF NOT EXISTS chunk_question_numbers (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    question_number INTEGER NOT NULL,
    PRIMARY KEY(chunk_id, question_number)
);

CREATE INDEX IF NOT EXISTS idx_lessons_date ON lessons(lesson_date);
CREATE INDEX IF NOT EXISTS idx_chunks_lesson ON chunks(lesson_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunk_topics_topic ON chunk_topics(topic);
CREATE INDEX IF NOT EXISTS idx_chunk_terms_term ON chunk_chemistry_terms(term);
CREATE INDEX IF NOT EXISTS idx_chunk_questions_number ON chunk_question_numbers(question_number);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^0-9a-z가-힣_-]+", "-", normalized)
    return normalized.strip("-") or "lesson"


def load_stage2_artifact(path: Path) -> tuple[Path, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"2단계 청크 파일을 찾을 수 없습니다: {path}")
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if payload.get("stage") != 2:
        raise ValueError("stage 값이 2인 청크 파일이 필요합니다.")
    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("2단계 청크 파일에 비어 있지 않은 chunks 배열이 필요합니다.")
    indexes = [chunk.get("chunk_index") for chunk in chunks]
    if any(not isinstance(index, int) or index < 0 for index in indexes):
        raise ValueError("모든 청크에 0 이상의 정수 chunk_index가 필요합니다.")
    if len(indexes) != len(set(indexes)):
        raise ValueError("chunk_index가 중복되었습니다.")
    if sorted(indexes) != list(range(len(indexes))):
        raise ValueError("chunk_index는 0부터 빠짐없이 이어져야 합니다.")
    if any(not str(chunk.get("text", "")).strip() for chunk in chunks):
        raise ValueError("내용이 비어 있는 청크가 있습니다.")
    return resolved, payload


def infer_topics(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).replace("열 에너지", "열에너지")
    topics = [
        topic
        for topic, keywords in TOPIC_RULES.items()
        if any(keyword.replace(" ", "") in normalized.replace(" ", "") for keyword in keywords)
    ]
    if QUESTION_NUMBER_RE.search(normalized) or any(word in normalized for word in ("보기", "정답", "문제")):
        topics.append("문제 풀이")
    return list(dict.fromkeys(topics)) or ["일반 수업 대화"]


def infer_content_types(text: str, speakers: list[str]) -> list[str]:
    content_types: list[str] = []
    if QUESTION_NUMBER_RE.search(text) or any(word in text for word in ("보기", "정답", "문제 풀이")):
        content_types.append("문제 풀이")
    if any(word in text for word in ("정의", "의미", "뜻", "원리", "개념", "설명을 하면")):
        content_types.append("개념 설명")
    if len(speakers) >= 2:
        content_types.append("교사-학생 대화")
    if any(word in text for word in ("숙제", "퀴즈", "정답률", "수업 들어")):
        content_types.append("수업 운영·피드백")
    return list(dict.fromkeys(content_types)) or ["교사 설명"]


def extract_chemistry_terms(text: str) -> list[str]:
    compact = unicodedata.normalize("NFKC", text).replace(" ", "")
    return [term for term in CHEMISTRY_TERMS if term.replace(" ", "") in compact]


def enrich_chunks(lesson_id: str, raw_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for raw in sorted(raw_chunks, key=lambda chunk: chunk["chunk_index"]):
        text = str(raw["text"]).strip()
        speakers = [str(speaker).strip() for speaker in raw.get("speakers", []) if str(speaker).strip()]
        question_numbers = sorted({int(number) for number in QUESTION_NUMBER_RE.findall(text)})
        topics = infer_topics(text)
        content_types = infer_content_types(text, speakers)
        chemistry_terms = extract_chemistry_terms(text)
        index = int(raw["chunk_index"])
        enriched.append(
            {
                "chunk_id": f"{lesson_id}:chunk:{index:04d}",
                "lesson_id": lesson_id,
                "chunk_index": index,
                "turn_start": raw.get("turn_start"),
                "turn_end": raw.get("turn_end"),
                "source_line_start": raw.get("source_line_start"),
                "source_line_end": raw.get("source_line_end"),
                "start_sec": raw.get("start_sec"),
                "end_sec": raw.get("end_sec"),
                "speakers": speakers,
                "topics": topics,
                "content_types": content_types,
                "chemistry_terms": chemistry_terms,
                "question_numbers": question_numbers,
                "char_count": len(text),
                "content_sha256": _sha256_text(text),
                "text": text,
            }
        )
    return enriched


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT INTO schema_info(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )
    connection.commit()
    return connection


def ingest_stage2_artifact(
    artifact_path: Path,
    database_path: Path,
    *,
    lesson_id: str | None = None,
    subject: str = "화학",
) -> dict[str, Any]:
    resolved_artifact, payload = load_stage2_artifact(artifact_path)
    metadata = payload.get("source_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    source_file = str(payload.get("source_file") or resolved_artifact.name)
    lesson_date = str(metadata.get("date") or "").strip() or None
    default_id = "_".join(part for part in (lesson_date, Path(source_file).stem) if part)
    resolved_lesson_id = _safe_id(lesson_id or default_id)
    title = str(metadata.get("title") or Path(source_file).stem).strip()
    language = str(metadata.get("language") or "ko").strip()
    chunks = enrich_chunks(resolved_lesson_id, payload["chunks"])
    now = datetime.now(timezone.utc).isoformat()
    database_path = database_path.expanduser().resolve()

    with connect_database(database_path) as connection:
        previous_row = connection.execute(
            "SELECT created_at FROM lessons WHERE lesson_id = ?", (resolved_lesson_id,)
        ).fetchone()
        previous_chunk_count = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE lesson_id = ?", (resolved_lesson_id,)
        ).fetchone()[0]
        created_at = previous_row["created_at"] if previous_row else now
        connection.execute(
            """
            INSERT INTO lessons(
                lesson_id, title, lesson_date, subject, language, source_file,
                stage2_artifact_sha256, source_metadata_json, chunking_config_json,
                created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lesson_id) DO UPDATE SET
                title = excluded.title,
                lesson_date = excluded.lesson_date,
                subject = excluded.subject,
                language = excluded.language,
                source_file = excluded.source_file,
                stage2_artifact_sha256 = excluded.stage2_artifact_sha256,
                source_metadata_json = excluded.source_metadata_json,
                chunking_config_json = excluded.chunking_config_json,
                updated_at = excluded.updated_at
            """,
            (
                resolved_lesson_id,
                title,
                lesson_date,
                subject,
                language,
                source_file,
                _sha256_file(resolved_artifact),
                _json(metadata),
                _json(payload.get("chunking_config", {})),
                created_at,
                now,
            ),
        )
        connection.execute("DELETE FROM chunks WHERE lesson_id = ?", (resolved_lesson_id,))
        for chunk in chunks:
            connection.execute(
                """
                INSERT INTO chunks(
                    chunk_id, lesson_id, chunk_index, turn_start, turn_end,
                    source_line_start, source_line_end, start_sec, end_sec,
                    speakers_json, topics_json, content_types_json,
                    chemistry_terms_json, question_numbers_json, char_count,
                    content_sha256, text
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"],
                    chunk["lesson_id"],
                    chunk["chunk_index"],
                    chunk["turn_start"],
                    chunk["turn_end"],
                    chunk["source_line_start"],
                    chunk["source_line_end"],
                    chunk["start_sec"],
                    chunk["end_sec"],
                    _json(chunk["speakers"]),
                    _json(chunk["topics"]),
                    _json(chunk["content_types"]),
                    _json(chunk["chemistry_terms"]),
                    _json(chunk["question_numbers"]),
                    chunk["char_count"],
                    chunk["content_sha256"],
                    chunk["text"],
                ),
            )
            connection.executemany(
                "INSERT INTO chunk_topics(chunk_id, topic) VALUES(?, ?)",
                ((chunk["chunk_id"], topic) for topic in chunk["topics"]),
            )
            connection.executemany(
                "INSERT INTO chunk_chemistry_terms(chunk_id, term) VALUES(?, ?)",
                ((chunk["chunk_id"], term) for term in chunk["chemistry_terms"]),
            )
            connection.executemany(
                "INSERT INTO chunk_question_numbers(chunk_id, question_number) VALUES(?, ?)",
                ((chunk["chunk_id"], number) for number in chunk["question_numbers"]),
            )

    return {
        "lesson_id": resolved_lesson_id,
        "expected_chunk_count": len(chunks),
        "previous_chunk_count_replaced": previous_chunk_count,
        "enriched_chunks": chunks,
        "database_path": str(database_path),
    }


def validate_lesson(
    database_path: Path,
    lesson_id: str,
    expected_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    with connect_database(database_path.expanduser().resolve()) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        stored_rows = connection.execute(
            "SELECT * FROM chunks WHERE lesson_id = ? ORDER BY chunk_index", (lesson_id,)
        ).fetchall()
        stored_count = len(stored_rows)
        expected_count = len(expected_chunks)
        matching_texts = sum(
            row["content_sha256"] == expected["content_sha256"] and row["text"] == expected["text"]
            for row, expected in zip(stored_rows, expected_chunks, strict=False)
        )
        metadata_complete = sum(
            bool(json.loads(row["speakers_json"]))
            and bool(json.loads(row["topics_json"]))
            and bool(json.loads(row["content_types_json"]))
            and bool(row["content_sha256"])
            for row in stored_rows
        )
        duplicate_indexes = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT chunk_index FROM chunks WHERE lesson_id = ?
                GROUP BY chunk_index HAVING COUNT(*) > 1
            )
            """,
            (lesson_id,),
        ).fetchone()[0]
        topic_distribution = dict(
            connection.execute(
                """
                SELECT topic, COUNT(*) AS count
                FROM chunk_topics JOIN chunks USING(chunk_id)
                WHERE lesson_id = ? GROUP BY topic ORDER BY count DESC, topic
                """,
                (lesson_id,),
            ).fetchall()
        )
        content_type_distribution: Counter[str] = Counter()
        for row in stored_rows:
            content_type_distribution.update(json.loads(row["content_types_json"]))
        question_numbers = [
            row[0]
            for row in connection.execute(
                """
                SELECT DISTINCT question_number
                FROM chunk_question_numbers JOIN chunks USING(chunk_id)
                WHERE lesson_id = ? ORDER BY question_number
                """,
                (lesson_id,),
            ).fetchall()
        ]
        total_lessons = connection.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        total_chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    chunk_count_match = stored_count == expected_count
    text_fidelity_rate = matching_texts / expected_count if expected_count else 0.0
    metadata_completeness_rate = metadata_complete / stored_count if stored_count else 0.0
    checks = [
        {"name": "sqlite_integrity", "actual": integrity, "criterion": "ok", "passed": integrity == "ok"},
        {
            "name": "foreign_key_errors",
            "actual": foreign_key_errors,
            "criterion": "= 0",
            "passed": foreign_key_errors == 0,
        },
        {
            "name": "chunk_count_match",
            "actual": f"{stored_count}/{expected_count}",
            "criterion": "stored = expected",
            "passed": chunk_count_match,
        },
        {
            "name": "text_fidelity_rate",
            "actual": round(text_fidelity_rate, 4),
            "criterion": "= 1.00",
            "passed": text_fidelity_rate == 1.0,
        },
        {
            "name": "metadata_completeness_rate",
            "actual": round(metadata_completeness_rate, 4),
            "criterion": "= 1.00",
            "passed": metadata_completeness_rate == 1.0,
        },
        {
            "name": "duplicate_chunk_indexes",
            "actual": duplicate_indexes,
            "criterion": "= 0",
            "passed": duplicate_indexes == 0,
        },
    ]
    return {
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "checks": checks,
        "database_totals": {"lessons": total_lessons, "chunks": total_chunks},
        "lesson_totals": {
            "chunks": stored_count,
            "topic_tags": sum(topic_distribution.values()),
            "question_numbers": question_numbers,
        },
        "topic_distribution": topic_distribution,
        "content_type_distribution": dict(content_type_distribution),
    }
