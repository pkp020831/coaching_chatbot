"""전사 대본을 읽고 대화 맥락을 보존한 검색 청크를 만든다."""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SPEAKER_RE = re.compile(r"^\*\*(?P<speaker>[^*:\n]+):\*\*\s*(?P<text>.*)$")
TIMED_TEXT_RE = re.compile(
    r"^\[(?P<start>\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?)\s*-\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?)\]\s*"
    r"\[(?P<speaker>[^]]+)\]\s*(?P<text>.+)$"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


@dataclass
class Turn:
    turn_index: int
    speaker: str
    text: str
    source_line: int
    start_sec: float | None = None
    end_sec: float | None = None


@dataclass
class Transcript:
    path: Path
    metadata: dict[str, Any]
    turns: list[Turn]
    parse_metrics: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_front_matter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return {}, 0

    metadata: dict[str, Any] = {}
    current_list: str | None = None
    for line in lines[1:end]:
        key_match = re.match(r"^(\w[\w_-]*):\s*(.*)$", line)
        if key_match:
            key, raw_value = key_match.groups()
            if raw_value:
                metadata[key] = _clean_scalar(raw_value)
                current_list = None
            else:
                current_list = key
                if key == "key_topics":
                    metadata[key] = []
            continue
        item_match = re.match(r"^\s{2}-\s+(.*)$", line)
        if item_match and current_list == "key_topics":
            metadata[current_list].append(_clean_scalar(item_match.group(1)))
    return metadata, end + 1


def _parse_time(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    pieces = str(value).strip().strip("[]").replace(",", ".").split(":")
    try:
        if len(pieces) == 2:
            hours = 0
            minutes, seconds = pieces
        elif len(pieces) == 3:
            hours, minutes, seconds = pieces
        else:
            return None
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _load_markdown(path: Path) -> Transcript:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    metadata, body_start = _parse_front_matter(lines)
    turns: list[Turn] = []
    candidate_lines = 0
    parsed_lines = 0
    unparsed_lines: list[int] = []

    for line_number, raw_line in enumerate(lines[body_start:], start=body_start + 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        candidate_lines += 1
        match = SPEAKER_RE.match(line)
        if match:
            turns.append(
                Turn(
                    turn_index=len(turns),
                    speaker=match.group("speaker").strip(),
                    text=match.group("text").strip(),
                    source_line=line_number,
                )
            )
            parsed_lines += 1
        elif turns:
            turns[-1].text = f"{turns[-1].text} {line}".strip()
            parsed_lines += 1
        else:
            unparsed_lines.append(line_number)

    warnings: list[str] = []
    if not turns:
        raise ValueError("'**화자:** 내용' 형식의 발화를 찾지 못했습니다.")
    if unparsed_lines:
        warnings.append(f"화자 발화로 해석하지 못한 줄: {unparsed_lines[:10]}")
    if turns[-1].text and turns[-1].text.rstrip()[-1] not in ".?!。！？…'\"”:)]":
        warnings.append("마지막 발화가 문장 중간에서 끝난 것으로 보입니다.")

    parse_rate = parsed_lines / candidate_lines if candidate_lines else 0.0
    return Transcript(
        path=path,
        metadata=metadata,
        turns=turns,
        parse_metrics={
            "format": "markdown",
            "candidate_lines": candidate_lines,
            "parsed_lines": parsed_lines,
            "line_parse_rate": round(parse_rate, 4),
            "turn_count": len(turns),
        },
        warnings=warnings,
    )


def _load_json(path: Path) -> Transcript:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    raw_segments = payload.get("segments", [])
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("JSON에 비어 있지 않은 'segments' 배열이 필요합니다.")
    turns: list[Turn] = []
    for index, segment in enumerate(raw_segments):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        turns.append(
            Turn(
                turn_index=len(turns),
                speaker=str(segment.get("speaker", "화자 미상")).strip() or "화자 미상",
                text=text,
                source_line=index + 1,
                start_sec=_parse_time(segment.get("start_sec", segment.get("start_time"))),
                end_sec=_parse_time(segment.get("end_sec", segment.get("end_time"))),
            )
        )
    if not turns:
        raise ValueError("JSON의 모든 전사 구간이 비어 있습니다.")
    metadata = {
        "title": payload.get("title") or payload.get("source", {}).get("file_name") or path.stem,
        "date": payload.get("date") or payload.get("created_at", "")[:10],
        "language": payload.get("language")
        or payload.get("transcription", {}).get("detected_language", "ko"),
        "key_topics": payload.get("key_topics", []),
    }
    return Transcript(
        path=path,
        metadata=metadata,
        turns=turns,
        parse_metrics={
            "format": "json",
            "candidate_segments": len(raw_segments),
            "parsed_segments": len(turns),
            "segment_parse_rate": round(len(turns) / len(raw_segments), 4),
            "turn_count": len(turns),
        },
    )


def _load_text(path: Path) -> Transcript:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    turns: list[Turn] = []
    nonempty = 0
    timed = 0
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        nonempty += 1
        match = TIMED_TEXT_RE.match(line)
        if match:
            timed += 1
            turns.append(
                Turn(
                    turn_index=len(turns),
                    speaker=match.group("speaker").strip(),
                    text=match.group("text").strip(),
                    source_line=line_number,
                    start_sec=_parse_time(match.group("start")),
                    end_sec=_parse_time(match.group("end")),
                )
            )
        else:
            turns.append(Turn(len(turns), "화자 미상", line, line_number))
    if not turns:
        raise ValueError("텍스트 대본이 비어 있습니다.")
    return Transcript(
        path=path,
        metadata={"title": path.stem, "language": "ko"},
        turns=turns,
        parse_metrics={
            "format": "text",
            "candidate_lines": nonempty,
            "parsed_lines": len(turns),
            "timed_line_rate": round(timed / nonempty, 4) if nonempty else 0.0,
            "turn_count": len(turns),
        },
    )


def load_transcript(path: Path) -> Transcript:
    """Markdown, 전사 JSON 또는 타임스탬프 TXT 대본을 읽는다."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"대본 파일을 찾을 수 없습니다: {path}")
    suffix = resolved.suffix.lower()
    if suffix == ".json":
        return _load_json(resolved)
    if suffix in {".md", ".markdown"}:
        return _load_markdown(resolved)
    if suffix == ".txt":
        return _load_text(resolved)
    raise ValueError("대본은 .md, .txt 또는 .json 형식이어야 합니다.")


def _split_long_text(text: str, target_chars: int) -> list[str]:
    sentences = SENTENCE_SPLIT_RE.split(text.strip())
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > target_chars:
            words = sentence.split()
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > target_chars:
                    pieces.append(current)
                    current = word
                else:
                    current = candidate
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > target_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [text]


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return float(ordered[index])


def build_chunks(
    transcript: Transcript,
    *,
    target_chars: int = 700,
    overlap_turns: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """발화 경계를 유지하면서 청크를 만들고 단계별 품질 지표를 반환한다."""
    if target_chars < 200:
        raise ValueError("target_chars는 200 이상이어야 합니다.")
    if overlap_turns < 0:
        raise ValueError("overlap_turns는 0 이상이어야 합니다.")

    units: list[Turn] = []
    for turn in transcript.turns:
        text_budget = max(100, target_chars - len(turn.speaker) - 2)
        for part in _split_long_text(turn.text, text_budget):
            units.append(
                Turn(
                    turn_index=turn.turn_index,
                    speaker=turn.speaker,
                    text=part,
                    source_line=turn.source_line,
                    start_sec=turn.start_sec,
                    end_sec=turn.end_sec,
                )
            )

    windows: list[list[Turn]] = []
    start = 0
    while start < len(units):
        end = start
        size = 0
        while end < len(units):
            rendered_size = len(units[end].speaker) + len(units[end].text) + 2
            separator_size = 1 if end > start else 0
            if end > start and size + separator_size + rendered_size > target_chars:
                break
            size += separator_size + rendered_size
            end += 1
        windows.append(units[start:end])
        if end >= len(units):
            break
        start = max(start + 1, end - overlap_turns)

    chunks: list[dict[str, Any]] = []
    for index, window in enumerate(windows):
        text = "\n".join(f"{turn.speaker}: {turn.text}" for turn in window)
        speakers = list(dict.fromkeys(turn.speaker for turn in window))
        starts = [turn.start_sec for turn in window if turn.start_sec is not None]
        ends = [turn.end_sec for turn in window if turn.end_sec is not None]
        chunks.append(
            {
                "chunk_index": index,
                "turn_start": window[0].turn_index,
                "turn_end": window[-1].turn_index,
                "source_line_start": min(turn.source_line for turn in window),
                "source_line_end": max(turn.source_line for turn in window),
                "start_sec": min(starts) if starts else None,
                "end_sec": max(ends) if ends else None,
                "speakers": speakers,
                "char_count": len(text),
                "text": text,
            }
        )

    sizes = [chunk["char_count"] for chunk in chunks]
    unique_texts = {chunk["text"] for chunk in chunks}
    unique_source_chars = (
        sum(len(turn.speaker) + len(turn.text) + 2 for turn in units) + max(0, len(units) - 1)
    )
    stored_chars = sum(sizes)
    covered_turns = {turn.turn_index for window in windows for turn in window}
    source_turn_coverage_rate = len(covered_turns) / len(transcript.turns) if transcript.turns else 0.0
    metrics = {
        "source_file": transcript.path.name,
        **transcript.parse_metrics,
        "source_turn_count": len(transcript.turns),
        "unit_count_after_long_turn_split": len(units),
        "chunk_count": len(chunks),
        "target_chars": target_chars,
        "overlap_turns": overlap_turns,
        "mean_chunk_chars": round(statistics.mean(sizes), 1) if sizes else 0.0,
        "median_chunk_chars": round(statistics.median(sizes), 1) if sizes else 0.0,
        "p95_chunk_chars": _percentile(sizes, 0.95),
        "source_turn_coverage_rate": round(source_turn_coverage_rate, 4),
        "empty_chunk_rate": round(sum(not chunk["text"].strip() for chunk in chunks) / len(chunks), 4)
        if chunks
        else 1.0,
        "oversize_chunk_rate": round(sum(size > target_chars for size in sizes) / len(sizes), 4)
        if sizes
        else 1.0,
        "duplicate_text_rate": round(1 - len(unique_texts) / len(chunks), 4) if chunks else 1.0,
        "estimated_overlap_rate": round(max(0, stored_chars - unique_source_chars) / stored_chars, 4)
        if stored_chars
        else 0.0,
        "warnings": transcript.warnings,
    }
    return chunks, metrics
