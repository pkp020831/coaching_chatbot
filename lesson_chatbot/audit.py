"""BM25 적중이 안정적인 근거에 의한 것인지 문항별로 감사한다."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from .database import connect_database
from .evaluation import load_evaluation_dataset
from .retrieval import TOKEN_RE, make_search_terms, search_bm25


GENERIC_EXACT_TERMS = {
    "오늘",
    "수업",
    "문제",
    "학생",
    "선생님",
    "퀴즈",
    "내용",
    "설명",
    "대답",
    "어떻게",
    "뭐야",
    "이유",
    "무엇",
}


def _term_sets(text: str) -> tuple[set[str], set[str]]:
    exact, ngrams = make_search_terms(text)
    return set(exact), set(ngrams)


def _chance_hit_probability(total: int, relevant: int, k: int) -> float:
    if relevant <= 0 or total <= 0:
        return 0.0
    if k >= total - relevant + 1:
        return 1.0
    return 1 - math.comb(total - relevant, k) / math.comb(total, k)


def _poisson_binomial_tail(probabilities: list[float], observed_or_more: int) -> float:
    distribution = [1.0] + [0.0] * len(probabilities)
    for probability in probabilities:
        for successes in range(len(probabilities), 0, -1):
            distribution[successes] = (
                distribution[successes] * (1 - probability)
                + distribution[successes - 1] * probability
            )
        distribution[0] *= 1 - probability
    return sum(distribution[observed_or_more:])


def _ablation_queries(question: str) -> list[str]:
    tokens = TOKEN_RE.findall(question)
    variants: list[str] = []
    for index in range(len(tokens)):
        candidate = " ".join(tokens[:index] + tokens[index + 1 :]).strip()
        if candidate and make_search_terms(candidate) != ([], []) and candidate not in variants:
            variants.append(candidate)
    return variants


def _classification(
    *,
    hit: bool,
    first_rank: int | None,
    distinctive_exact_count: int,
    ngram_count: int,
    ablation_stability: float,
) -> str:
    if not hit:
        return "실패"
    if (
        first_rank is not None
        and first_rank <= 3
        and distinctive_exact_count >= 1
        and ablation_stability >= 0.7
    ):
        return "강건"
    if (
        first_rank is not None
        and first_rank <= 5
        and (distinctive_exact_count >= 1 or ngram_count >= 3)
        and ablation_stability >= 0.5
    ):
        return "보통"
    return "취약"


def audit_bm25_hits(
    database_path: Path,
    dataset_path: Path,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    if not 1 <= top_k <= 50:
        raise ValueError("top_k는 1~50 사이여야 합니다.")
    items = load_evaluation_dataset(dataset_path, database_path)
    with connect_database(database_path.expanduser().resolve()) as connection:
        rows = connection.execute("SELECT chunk_id, text FROM chunks").fetchall()
    text_by_id = {row["chunk_id"]: row["text"] for row in rows}
    total_chunks = len(rows)

    audited: list[dict[str, Any]] = []
    random_probabilities_top1: list[float] = []
    random_probabilities_topk: list[float] = []
    for item in items:
        relevant_ids = set(item["relevant_chunk_ids"])
        original = search_bm25(database_path, item["question"], top_k=top_k)
        returned = original["results"]
        first_relevant = next((row for row in returned if row["chunk_id"] in relevant_ids), None)
        first_rank = first_relevant["rank"] if first_relevant else None
        hit = first_relevant is not None

        relevant_text = "\n".join(text_by_id[chunk_id] for chunk_id in relevant_ids)
        query_exact, query_ngrams = _term_sets(item["question"])
        relevant_exact, relevant_ngrams = _term_sets(relevant_text)
        exact_matches = sorted(term[1:] for term in query_exact & relevant_exact)
        distinctive_exact = sorted(term for term in exact_matches if term not in GENERIC_EXACT_TERMS)
        ngram_matches = query_ngrams & relevant_ngrams

        keyword_matches = 0
        for keyword in item["target_keywords"]:
            keyword_exact, keyword_ngrams = _term_sets(keyword)
            keyword_matches += int(bool((keyword_exact & relevant_exact) or (keyword_ngrams & relevant_ngrams)))
        keyword_evidence_rate = keyword_matches / len(item["target_keywords"])

        ablations = _ablation_queries(item["question"])
        ablation_hits = 0
        for ablated_query in ablations:
            ablated_result = search_bm25(database_path, ablated_query, top_k=top_k)
            ablation_hits += int(
                any(row["chunk_id"] in relevant_ids for row in ablated_result["results"])
            )
        ablation_stability = ablation_hits / len(ablations) if ablations else float(hit)

        relevant_score = first_relevant["score"] if first_relevant else None
        best_nonrelevant_score = next(
            (row["score"] for row in returned if row["chunk_id"] not in relevant_ids), None
        )
        score_ratio = (
            relevant_score / best_nonrelevant_score
            if relevant_score is not None and best_nonrelevant_score not in (None, 0)
            else None
        )
        chance_top1 = len(relevant_ids) / total_chunks
        chance_topk = _chance_hit_probability(total_chunks, len(relevant_ids), top_k)
        random_probabilities_top1.append(chance_top1)
        random_probabilities_topk.append(chance_topk)
        classification = _classification(
            hit=hit,
            first_rank=first_rank,
            distinctive_exact_count=len(distinctive_exact),
            ngram_count=len(ngram_matches),
            ablation_stability=ablation_stability,
        )
        audited.append(
            {
                "id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "relevant_chunk_ids": item["relevant_chunk_ids"],
                "hit_at_k": hit,
                "first_relevant_rank": first_rank,
                "first_relevant_chunk_id": first_relevant["chunk_id"] if first_relevant else None,
                "first_relevant_score": relevant_score,
                "best_nonrelevant_score": best_nonrelevant_score,
                "relevant_to_best_nonrelevant_score_ratio": round(score_ratio, 4)
                if score_ratio is not None
                else None,
                "query_relevant_exact_matches": exact_matches,
                "distinctive_exact_matches": distinctive_exact,
                "query_relevant_ngram_match_count": len(ngram_matches),
                "target_keyword_evidence_rate": round(keyword_evidence_rate, 4),
                "leave_one_token_out": {
                    "trial_count": len(ablations),
                    "hit_count": ablation_hits,
                    "stability": round(ablation_stability, 4),
                },
                "random_hit_probability_at_k": round(chance_topk, 4),
                "classification": classification,
            }
        )

    class_counts = Counter(item["classification"] for item in audited)
    observed_top1 = sum(item["first_relevant_rank"] == 1 for item in audited)
    observed_topk = sum(item["hit_at_k"] for item in audited)
    p_value_top1 = _poisson_binomial_tail(random_probabilities_top1, observed_top1)
    p_value_topk = _poisson_binomial_tail(random_probabilities_topk, observed_topk)
    return {
        "stage": 4,
        "audit_type": "BM25 hit robustness and chance baseline",
        "dataset_file": dataset_path.name,
        "top_k": top_k,
        "question_count": len(audited),
        "summary": {
            "classification_counts": dict(class_counts),
            "observed_top1_hits": observed_top1,
            "observed_top_k_hits": observed_topk,
            "mean_leave_one_token_out_stability": round(
                statistics.mean(item["leave_one_token_out"]["stability"] for item in audited), 4
            ),
            "random_expected_top1_hits": round(sum(random_probabilities_top1), 4),
            "random_expected_top_k_hits": round(sum(random_probabilities_topk), 4),
            "random_tail_probability_top1": p_value_top1,
            "random_tail_probability_top_k": p_value_topk,
            "target_or_gold_used_for_retrieval": False,
        },
        "classification_rule": {
            "강건": "Top-3 적중, 의미 있는 동일 어절 1개 이상, 단어 하나 제거 안정성 70% 이상",
            "보통": "Top-5 적중, 동일 어절 또는 3개 이상 n-gram 근거, 안정성 50% 이상",
            "취약": "적중했지만 위 근거·안정성 기준 미달",
            "실패": f"Top-{top_k} 안에 정답 청크 없음",
        },
        "per_question": audited,
    }
