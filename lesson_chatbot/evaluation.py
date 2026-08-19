"""정답 청크가 표시된 JSON으로 BM25 검색 품질을 평가한다."""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from .database import connect_database
from .retrieval import make_search_terms, search_bm25


REQUIRED_FIELDS = {
    "id",
    "category",
    "question",
    "relevant_chunk_ids",
    "target_keywords",
    "gold_answer",
}
ALLOWED_CATEGORIES = {"수업 운영·피드백", "개념 설명", "문제 풀이", "교사-학생 대화"}
QUESTION_ID_RE = re.compile(r"^Q\d{2}$")


def load_evaluation_dataset(path: Path, database_path: Path) -> list[dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"평가 JSON을 찾을 수 없습니다: {path}")
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("평가 JSON 최상위 값은 비어 있지 않은 배열이어야 합니다.")

    with connect_database(database_path.expanduser().resolve()) as connection:
        valid_chunk_ids = {row[0] for row in connection.execute("SELECT chunk_id FROM chunks")}

    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"평가 문항 {index}는 JSON 객체여야 합니다.")
        missing_fields = REQUIRED_FIELDS - raw.keys()
        if missing_fields:
            raise ValueError(f"평가 문항 {index}에 필드가 없습니다: {sorted(missing_fields)}")
        item_id = str(raw["id"]).strip()
        if not QUESTION_ID_RE.fullmatch(item_id):
            raise ValueError(f"평가 문항 ID 형식이 잘못되었습니다: {item_id} (예: Q01)")
        if item_id in seen_ids:
            raise ValueError(f"평가 문항 ID가 중복되었습니다: {item_id}")
        seen_ids.add(item_id)

        category = str(raw["category"]).strip()
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"{item_id}의 category '{category}'는 코드 용어가 아닙니다. "
                f"허용값: {sorted(ALLOWED_CATEGORIES)}"
            )
        question = str(raw["question"]).strip()
        relevant_chunk_ids = list(dict.fromkeys(str(value).strip() for value in raw["relevant_chunk_ids"]))
        target_keywords = list(dict.fromkeys(str(value).strip() for value in raw["target_keywords"]))
        gold_answer = str(raw["gold_answer"]).strip()
        if not question or not relevant_chunk_ids or not target_keywords or not gold_answer:
            raise ValueError(f"{item_id}에 빈 question, 정답 청크, 키워드 또는 모범 답안이 있습니다.")
        unknown_ids = sorted(set(relevant_chunk_ids) - valid_chunk_ids)
        if unknown_ids:
            raise ValueError(f"{item_id}에 DB에 없는 relevant_chunk_ids가 있습니다: {unknown_ids}")
        normalized.append(
            {
                "id": item_id,
                "category": category,
                "question": question,
                "relevant_chunk_ids": relevant_chunk_ids,
                "target_keywords": target_keywords,
                "gold_answer": gold_answer,
            }
        )
    return normalized


def _ranking_metrics(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> dict[str, float]:
    top_ids = retrieved_ids[:k]
    relevant_ranks = [rank for rank, chunk_id in enumerate(top_ids, start=1) if chunk_id in relevant_ids]
    hit_count = len(relevant_ranks)
    dcg = sum(1 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return {
        "hit": 1.0 if relevant_ranks else 0.0,
        "precision": hit_count / k,
        "recall": hit_count / len(relevant_ids),
        "mrr": 1 / relevant_ranks[0] if relevant_ranks else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
    }


def _term_set(text: str) -> set[str]:
    exact, ngrams = make_search_terms(text)
    return set(exact) | set(ngrams)


def evaluate_bm25(
    database_path: Path,
    dataset_path: Path,
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
) -> dict[str, Any]:
    if not k_values or any(k < 1 or k > 50 for k in k_values):
        raise ValueError("k 값은 1~50 사이의 정수여야 합니다.")
    k_values = tuple(sorted(set(k_values)))
    items = load_evaluation_dataset(dataset_path, database_path)
    max_k = max(k_values)

    with connect_database(database_path.expanduser().resolve()) as connection:
        relevant_text_by_id = {
            row["chunk_id"]: row["text"]
            for row in connection.execute("SELECT chunk_id, text FROM chunks")
        }

    per_question: list[dict[str, Any]] = []
    latency_values: list[float] = []
    total_keywords = 0
    tokenized_keywords = 0
    matched_keywords = 0
    for item in items:
        search_result = search_bm25(database_path, item["question"], top_k=max_k)
        latency_values.append(search_result["query_latency_ms"])
        retrieved = search_result["results"]
        retrieved_ids = [result["chunk_id"] for result in retrieved]
        relevant_ids = set(item["relevant_chunk_ids"])
        item_metrics = {
            f"@{k}": _ranking_metrics(retrieved_ids, relevant_ids, k) for k in k_values
        }

        relevant_terms: set[str] = set()
        for chunk_id in relevant_ids:
            relevant_terms.update(_term_set(relevant_text_by_id[chunk_id]))
        missing_keywords: list[str] = []
        keyword_details: list[dict[str, Any]] = []
        for keyword in item["target_keywords"]:
            keyword_terms = _term_set(keyword)
            tokenized = bool(keyword_terms)
            matched = bool(keyword_terms & relevant_terms)
            total_keywords += 1
            tokenized_keywords += int(tokenized)
            matched_keywords += int(matched)
            if not matched:
                missing_keywords.append(keyword)
            keyword_details.append(
                {"keyword": keyword, "tokenized": tokenized, "matched_relevant_text": matched}
            )

        first_relevant_rank = next(
            (rank for rank, chunk_id in enumerate(retrieved_ids, start=1) if chunk_id in relevant_ids),
            None,
        )
        per_question.append(
            {
                **item,
                "first_relevant_rank": first_relevant_rank,
                "candidate_count": search_result["candidate_count"],
                "returned": [
                    {
                        "rank": result["rank"],
                        "chunk_id": result["chunk_id"],
                        "score": result["score"],
                    }
                    for result in retrieved
                ],
                "metrics": item_metrics,
                "keyword_validation": keyword_details,
                "missing_target_keywords_in_relevant_text": missing_keywords,
                "query_latency_ms": search_result["query_latency_ms"],
            }
        )

    aggregate: dict[str, dict[str, float]] = {}
    for k in k_values:
        metric_key = f"@{k}"
        aggregate[metric_key] = {
            name: round(statistics.mean(item["metrics"][metric_key][name] for item in per_question), 4)
            for name in ("hit", "precision", "recall", "mrr", "ndcg")
        }

    category_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in per_question:
        category_items[item["category"]].append(item)
    category_summary: dict[str, dict[str, Any]] = {}
    max_key = f"@{max_k}"
    for category, grouped in sorted(category_items.items()):
        category_summary[category] = {
            "question_count": len(grouped),
            "hit": round(statistics.mean(item["metrics"][max_key]["hit"] for item in grouped), 4),
            "recall": round(statistics.mean(item["metrics"][max_key]["recall"] for item in grouped), 4),
            "mrr": round(statistics.mean(item["metrics"][max_key]["mrr"] for item in grouped), 4),
            "ndcg": round(statistics.mean(item["metrics"][max_key]["ndcg"] for item in grouped), 4),
        }

    failed_at_max_k = [
        item["id"] for item in per_question if item["metrics"][max_key]["hit"] == 0.0
    ]
    return {
        "stage": 4,
        "evaluation_type": "BM25 retrieval",
        "dataset_file": dataset_path.name,
        "question_count": len(items),
        "k_values": list(k_values),
        "summary": aggregate,
        "category_summary_at_max_k": category_summary,
        "tokenizer_validation": {
            "target_keyword_count": total_keywords,
            "tokenization_rate": round(tokenized_keywords / total_keywords, 4) if total_keywords else 0.0,
            "relevant_text_lexical_match_rate": round(matched_keywords / total_keywords, 4)
            if total_keywords
            else 0.0,
        },
        "latency": {
            "mean_query_ms": round(statistics.mean(latency_values), 2),
            "p95_query_ms": round(sorted(latency_values)[max(0, math.ceil(len(latency_values) * 0.95) - 1)], 2),
        },
        "failed_question_ids_at_max_k": failed_at_max_k,
        "per_question": per_question,
    }
