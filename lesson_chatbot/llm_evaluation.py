"""5단계 서술형 답변을 교사 기준에 맞춰 평가하고 피드백을 누적한다.

이 모듈의 "학습"은 모델 파인튜닝이 아니다. 교사 채점 예시를 평가 프롬프트에
추가하고, 교사와 평가 LLM 사이의 점수 편향 및 항목 가중치를 통계적으로 보정한다.
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


RUBRIC: dict[str, dict[str, Any]] = {
    "class_grounding": {
        "label": "수업 근거 충실성",
        "weight": 0.25,
        "description": "수업 사실·숙제·휴강 등을 검색 근거 없이 꾸며내지 않고 근거와 답변이 일치한다.",
    },
    "scope_boundary": {
        "label": "범위 판단과 안전성",
        "weight": 0.20,
        "description": "직접 언급, 간접 추론, 관련 일반 이론, 무관한 질문을 구분하고 불확실성을 밝힌다.",
    },
    "correctness_relevance": {
        "label": "정확성과 관련성",
        "weight": 0.20,
        "description": "질문에 맞고 화학적으로 정확하며 모순되거나 엉뚱한 설명이 없다.",
    },
    "completeness_actionability": {
        "label": "충분성과 실행 가능성",
        "weight": 0.15,
        "description": "필요한 설명·풀이·과제를 구체적으로 제공하고 학생이 다음 행동을 알 수 있다.",
    },
    "student_clarity": {
        "label": "학생 눈높이와 명료성",
        "weight": 0.10,
        "description": "학생이 이해하기 쉬운 구조와 표현을 사용하고 불필요하게 장황하지 않다.",
    },
    "citation_traceability": {
        "label": "근거 추적 가능성",
        "weight": 0.10,
        "description": "수업 근거를 사용했다면 유효한 청크 ID로 어떤 내용에 근거했는지 확인할 수 있다.",
    },
}

SCORE_GUIDE = {
    1: "중대한 오류 또는 요구 위반",
    2: "핵심 결함이 많아 그대로 사용하기 어려움",
    3: "최소 요구는 충족하지만 뚜렷한 보완 필요",
    4: "작은 보완만 필요한 좋은 답변",
    5: "정확하고 안전하며 구체적인 모범 답변",
}

EXPECTED_BEHAVIORS = {"direct", "inferred", "related_general", "out_of_scope"}


def _string_list(value: Any, field: str, item_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{item_id}의 {field}는 배열이어야 합니다.")
    return [str(item).strip() for item in value if str(item).strip()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("답변 평가 JSON 최상위 값은 비어 있지 않은 배열이어야 합니다.")
    return [validate_answer_item(item, index) for index, item in enumerate(payload, start=1)]


def validate_answer_item(raw: Any, index: int = 1) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"평가 항목 {index}는 JSON 객체여야 합니다.")
    required = {"id", "question", "answer", "retrieved_chunks"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"평가 항목 {index}에 필드가 없습니다: {sorted(missing)}")
    item_id = str(raw["id"]).strip()
    question = str(raw["question"]).strip()
    answer = str(raw["answer"]).strip()
    if not item_id or not question or not answer:
        raise ValueError(f"평가 항목 {index}의 id, question, answer는 비어 있을 수 없습니다.")

    chunks = raw["retrieved_chunks"]
    if not isinstance(chunks, list):
        raise ValueError(f"{item_id}의 retrieved_chunks는 배열이어야 합니다.")
    normalized_chunks: list[dict[str, str]] = []
    seen_chunk_ids: set[str] = set()
    for chunk_index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict) or not str(chunk.get("chunk_id", "")).strip():
            raise ValueError(f"{item_id}의 검색 청크 {chunk_index}에 chunk_id가 없습니다.")
        chunk_id = str(chunk["chunk_id"]).strip()
        text = str(chunk.get("text", "")).strip()
        if not text:
            raise ValueError(f"{item_id}의 검색 청크 {chunk_id}에 text가 없습니다.")
        if chunk_id not in seen_chunk_ids:
            normalized_chunks.append({"chunk_id": chunk_id, "text": text})
            seen_chunk_ids.add(chunk_id)

    expected_behavior = str(raw.get("expected_behavior", "")).strip() or None
    if expected_behavior is not None and expected_behavior not in EXPECTED_BEHAVIORS:
        raise ValueError(
            f"{item_id}의 expected_behavior가 잘못되었습니다: {expected_behavior}; "
            f"허용값={sorted(EXPECTED_BEHAVIORS)}"
        )
    return {
        "id": item_id,
        "category": str(raw.get("category", "미분류")).strip() or "미분류",
        "question": question,
        "answer": answer,
        "retrieved_chunks": normalized_chunks,
        "expected_behavior": expected_behavior,
        "gold_answer": str(raw.get("gold_answer", "")).strip() or None,
        "required_points": _string_list(raw.get("required_points"), "required_points", item_id),
        "forbidden_claims": _string_list(raw.get("forbidden_claims"), "forbidden_claims", item_id),
        "grading_focus": _string_list(raw.get("grading_focus"), "grading_focus", item_id),
    }


def validate_scores(raw_scores: Mapping[str, Any]) -> dict[str, float]:
    missing = set(RUBRIC) - set(raw_scores)
    if missing:
        raise ValueError(f"채점 항목이 누락되었습니다: {sorted(missing)}")
    scores: dict[str, float] = {}
    for dimension in RUBRIC:
        try:
            score = float(raw_scores[dimension])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{dimension} 점수는 숫자여야 합니다.") from error
        if not 1 <= score <= 5:
            raise ValueError(f"{dimension} 점수는 1~5 사이여야 합니다: {score}")
        scores[dimension] = score
    return scores


def weighted_score(scores: Mapping[str, float], weights: Mapping[str, float]) -> float:
    weight_sum = sum(float(weights[name]) for name in RUBRIC)
    if weight_sum <= 0:
        raise ValueError("평가 가중치 합은 0보다 커야 합니다.")
    return round(
        sum(float(scores[name]) / 5.0 * float(weights[name]) for name in RUBRIC)
        / weight_sum
        * 100,
        2,
    )


def load_feedback(path: Path) -> list[dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(resolved.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            record["teacher_scores"] = validate_scores(record["teacher_scores"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"교사 피드백 {path}:{line_number} 형식 오류: {error}") from error
        records.append(record)
    return records


def append_feedback(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    teacher_scores = validate_scores(record.get("teacher_scores", {}))
    evaluator_scores = record.get("evaluator_scores")
    normalized_evaluator = validate_scores(evaluator_scores) if evaluator_scores is not None else None
    overall = record.get("teacher_overall_score")
    if overall is not None:
        overall = float(overall)
        if not 0 <= overall <= 100:
            raise ValueError("teacher_overall_score는 0~100 사이여야 합니다.")
    normalized = {
        "feedback_id": str(record.get("feedback_id") or uuid.uuid4()),
        "recorded_at": str(record.get("recorded_at") or _now_iso()),
        "question_id": str(record.get("question_id", "")).strip(),
        "category": str(record.get("category", "미분류")).strip() or "미분류",
        "question": str(record.get("question", "")).strip(),
        "answer": str(record.get("answer", "")).strip(),
        "expected_behavior": record.get("expected_behavior"),
        "teacher_scores": teacher_scores,
        "teacher_overall_score": overall,
        "teacher_pass": bool(record.get("teacher_pass", weighted_score(
            teacher_scores, {name: spec["weight"] for name, spec in RUBRIC.items()}
        ) >= 70)),
        "teacher_notes": str(record.get("teacher_notes", "")).strip(),
        "evaluator_scores": normalized_evaluator,
    }
    if not normalized["question_id"] or not normalized["question"] or not normalized["answer"]:
        raise ValueError("question_id, question, answer는 비어 있을 수 없습니다.")
    if normalized["expected_behavior"] not in EXPECTED_BEHAVIORS | {None}:
        raise ValueError("expected_behavior가 허용값이 아닙니다.")
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    return normalized


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def build_calibration_profile(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)
    default_weights = {name: float(spec["weight"]) for name, spec in RUBRIC.items()}
    paired = [record for record in records if record.get("evaluator_scores")]
    offsets: dict[str, float] = {}
    for dimension in RUBRIC:
        differences = [
            float(record["teacher_scores"][dimension]) - float(record["evaluator_scores"][dimension])
            for record in paired
        ]
        offsets[dimension] = round(max(-1.0, min(1.0, statistics.mean(differences))), 3) if differences else 0.0

    overall_records = [record for record in records if record.get("teacher_overall_score") is not None]
    weights = dict(default_weights)
    weight_method = "default"
    if len(overall_records) >= 6:
        targets = [float(record["teacher_overall_score"]) for record in overall_records]
        correlations = {
            dimension: max(0.05, _pearson(
                [float(record["teacher_scores"][dimension]) for record in overall_records], targets
            ))
            for dimension in RUBRIC
        }
        correlation_sum = sum(correlations.values())
        learned = {name: value / correlation_sum for name, value in correlations.items()}
        # 소량 데이터의 과적합을 막기 위해 기본 가중치와 절반씩 혼합한다.
        weights = {name: round(default_weights[name] * 0.5 + learned[name] * 0.5, 4) for name in RUBRIC}
        normalized_sum = sum(weights.values())
        weights = {name: round(value / normalized_sum, 4) for name, value in weights.items()}
        weight_method = "teacher_overall_correlation_shrunk_50pct"

    return {
        "feedback_count": len(records),
        "paired_score_count": len(paired),
        "overall_score_count": len(overall_records),
        "score_offsets": offsets,
        "weights": weights,
        "weight_method": weight_method,
        "learning_note": "파인튜닝이 아니라 교사 사례 few-shot, 점수 편향, 가중치 통계 보정입니다.",
    }


def select_feedback_examples(records: Iterable[Mapping[str, Any]], limit: int = 6) -> list[Mapping[str, Any]]:
    if limit < 0:
        raise ValueError("예시 개수는 0 이상이어야 합니다.")
    records = list(records)
    selected: list[Mapping[str, Any]] = []
    # 최근 사례를 우선하되, 행동 유형이 한쪽으로만 몰리지 않게 먼저 하나씩 고른다.
    for behavior in EXPECTED_BEHAVIORS:
        match = next((record for record in reversed(records) if record.get("expected_behavior") == behavior), None)
        if match is not None and match not in selected:
            selected.append(match)
    for record in reversed(records):
        if record not in selected:
            selected.append(record)
        if len(selected) >= limit:
            break
    return selected[:limit]


def build_evaluator_prompt(
    item: Mapping[str, Any],
    profile: Mapping[str, Any],
    examples: Iterable[Mapping[str, Any]],
) -> str:
    rubric_payload = {
        name: {
            "label": spec["label"],
            "description": spec["description"],
            "current_weight": profile["weights"][name],
        }
        for name, spec in RUBRIC.items()
    }
    example_payload = [
        {
            "question": record.get("question"),
            "answer": record.get("answer"),
            "expected_behavior": record.get("expected_behavior"),
            "teacher_scores": record.get("teacher_scores"),
            "teacher_pass": record.get("teacher_pass"),
            "teacher_notes": record.get("teacher_notes"),
        }
        for record in examples
    ]
    evaluation_input = {
        "id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "answer": item["answer"],
        "expected_behavior": item.get("expected_behavior"),
        "retrieved_chunks": item["retrieved_chunks"],
        "gold_answer_for_evaluation_only": item.get("gold_answer"),
        "required_points_for_evaluation_only": item.get("required_points", []),
        "forbidden_claims_for_evaluation_only": item.get("forbidden_claims", []),
        "grading_focus_for_evaluation_only": item.get("grading_focus", []),
    }
    return f"""당신은 한국어 화학 과외 챗봇의 답변 평가자다.
수업 근거와 답변을 엄격히 비교하고 각 항목을 1~5점으로 채점하라.

범위 판단 원칙:
- direct: 수업에서 직접 확인되는 사실만 단정한다.
- inferred: 여러 수업 근거에서 합리적으로 도출했음을 명시한다.
- related_general: 수업과 관련된 일반 화학 지식임을 수업 언급과 구분한다.
- out_of_scope: 수업과 무관하거나 근거가 전혀 없으면 이번 수업에서 다루지 않았다고 안전하게 답한다.
- 숙제, 휴강, 일정 같은 운영 사실은 일반 지식으로 보충하거나 추측하면 안 된다.
- out_of_scope로 안전하게 거절한 답변은 사용할 수업 근거가 없으므로, 청크 인용이 없다는 이유만으로 감점하지 않는다.
- gold_answer는 평가 참고 자료일 뿐이며, 검색이나 답변 생성에 사용됐다고 가정하지 않는다.

평가표:
{json.dumps(rubric_payload, ensure_ascii=False, indent=2)}

점수 의미:
{json.dumps(SCORE_GUIDE, ensure_ascii=False, indent=2)}

교사 채점 사례(없을 수 있음):
{json.dumps(example_payload, ensure_ascii=False, indent=2)}

평가 대상:
{json.dumps(evaluation_input, ensure_ascii=False, indent=2)}

다음 JSON 객체만 출력하라:
{{
  "scores": {{"class_grounding": 1, "scope_boundary": 1, "correctness_relevance": 1,
               "completeness_actionability": 1, "student_clarity": 1, "citation_traceability": 1}},
  "rationales": {{"class_grounding": "근거", "scope_boundary": "근거",
                    "correctness_relevance": "근거", "completeness_actionability": "근거",
                    "student_clarity": "근거", "citation_traceability": "근거"}},
  "cited_chunk_ids": ["실제로 사용한 유효 청크 ID"],
  "strengths": ["장점"],
  "problems": ["문제점"],
  "improvement": "개선 방향"
}}"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"평가 LLM이 유효한 JSON을 반환하지 않았습니다: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("평가 LLM 응답은 JSON 객체여야 합니다.")
    return payload


def apply_calibration(
    raw_scores: Mapping[str, Any], profile: Mapping[str, Any]
) -> tuple[dict[str, float], float, bool]:
    raw = validate_scores(raw_scores)
    calibrated = {
        dimension: round(max(1.0, min(5.0, raw[dimension] + float(profile["score_offsets"][dimension]))), 2)
        for dimension in RUBRIC
    }
    overall = weighted_score(calibrated, profile["weights"])
    hard_gate = calibrated["class_grounding"] >= 3 and calibrated["scope_boundary"] >= 3
    return calibrated, overall, bool(overall >= 70 and hard_gate)


def evaluate_answers(
    items: Iterable[Mapping[str, Any]],
    evaluator: Callable[[str], str | Mapping[str, Any]],
    *,
    feedback_records: Iterable[Mapping[str, Any]] = (),
    example_limit: int = 6,
) -> dict[str, Any]:
    items = [validate_answer_item(item, index) for index, item in enumerate(items, start=1)]
    feedback_records = list(feedback_records)
    profile = build_calibration_profile(feedback_records)
    examples = select_feedback_examples(feedback_records, example_limit)
    per_question: list[dict[str, Any]] = []
    for item in items:
        prompt = build_evaluator_prompt(item, profile, examples)
        raw_response = evaluator(prompt)
        parsed = dict(raw_response) if isinstance(raw_response, Mapping) else _extract_json(raw_response)
        raw_scores = validate_scores(parsed.get("scores", {}))
        calibrated_scores, overall, passed = apply_calibration(raw_scores, profile)
        valid_chunk_ids = {chunk["chunk_id"] for chunk in item["retrieved_chunks"]}
        cited_ids = [str(value) for value in parsed.get("cited_chunk_ids", [])]
        invalid_citations = sorted(set(cited_ids) - valid_chunk_ids)
        if invalid_citations:
            calibrated_scores["citation_traceability"] = 1.0
            overall = weighted_score(calibrated_scores, profile["weights"])
            passed = bool(overall >= 70 and calibrated_scores["class_grounding"] >= 3
                          and calibrated_scores["scope_boundary"] >= 3)
        per_question.append({
            **item,
            "evaluator_raw_scores": raw_scores,
            "calibrated_scores": calibrated_scores,
            "overall_score": overall,
            "passed": passed,
            "rationales": parsed.get("rationales", {}),
            "cited_chunk_ids": cited_ids,
            "invalid_cited_chunk_ids": invalid_citations,
            "strengths": parsed.get("strengths", []),
            "problems": parsed.get("problems", []),
            "improvement": str(parsed.get("improvement", "")),
        })
    return {
        "stage": 5,
        "evaluation_type": "LLM answer quality with teacher calibration",
        "question_count": len(per_question),
        "rubric": RUBRIC,
        "calibration_profile": profile,
        "summary": {
            "mean_score": round(statistics.mean(row["overall_score"] for row in per_question), 2),
            "pass_rate": round(statistics.mean(row["passed"] for row in per_question), 4),
        },
        "per_question": per_question,
    }
