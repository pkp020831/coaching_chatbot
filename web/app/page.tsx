"use client";

import { FormEvent, useState } from "react";

type SearchItem = {
  rank: number;
  chunk_id: string;
  lesson_id: string;
  title: string;
  lesson_date: string | null;
  chunk_index: number;
  score: number;
  source_line_start: number | null;
  source_line_end: number | null;
  topics: string[];
  question_numbers: number[];
  text: string;
};

type AnswerResponse = {
  question: string;
  scope: "DIRECT_CLASS" | "INFERRED_CLASS" | "RELATED_GENERAL" | "COURSE_INFO_MISSING" | "OUT_OF_SCOPE";
  answer: string;
  evidence_note: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  used_general_knowledge: boolean;
  cited_chunk_ids: string[];
  evidence: SearchItem[];
  retrieval: {
    top_k: number;
    candidate_count: number;
    returned_count: number;
    query_latency_ms: number;
  };
  generation: { model: string; latency_ms: number };
};

const examples = [
  "열용량의 정확한 정의가 뭐야?",
  "113번에서 주위 온도가 낮아지는 이유는?",
  "다음 주 수업은 휴강이야?",
];

const scopeLabels: Record<AnswerResponse["scope"], string> = {
  DIRECT_CLASS: "수업 직접 근거",
  INFERRED_CLASS: "수업 내용으로 추론",
  RELATED_GENERAL: "관련 이론 보충",
  COURSE_INFO_MISSING: "운영 정보 확인 필요",
  OUT_OF_SCOPE: "수업 범위 밖",
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(3);
  const [response, setResponse] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(event?: FormEvent, override?: string) {
    event?.preventDefault();
    const searchText = (override ?? query).trim();
    if (!searchText) {
      setError("질문을 입력해 주세요.");
      return;
    }
    if (override) setQuery(override);
    setLoading(true);
    setError("");
    try {
      const result = await fetch("http://127.0.0.1:8765/api/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: searchText, top_k: topK }),
      });
      const body = await result.json();
      if (!result.ok) throw new Error(body.error ?? "검색 중 오류가 발생했습니다.");
      setResponse(body);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "검색 서버에 연결할 수 없습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="화학 수업 챗봇 홈">
          <span className="brandMark">C</span>
          <span>화학 수업 챗봇</span>
        </a>
        <span className="localBadge"><i />BM25 근거 + Gemini 답변</span>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow">CHEMISTRY CLASS Q&amp;A</div>
        <h1>수업에서 배운 내용을<br /><em>구체적으로 물어보세요.</em></h1>
        <p className="intro">
          수업 대본에서 BM25로 근거를 찾고 서술형으로 설명합니다. 직접 언급되지 않은
          관련 개념은 구분해 보충하고, 확인할 수 없는 운영 정보는 추측하지 않아요.
        </p>

        <form className="searchBox" onSubmit={(event) => search(event)}>
          <label htmlFor="search-query">수업 내용 질문</label>
          <div className="searchRow">
            <input
              id="search-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="예: 열용량이 무엇인가요?"
              autoComplete="off"
            />
            <select
              aria-label="검색 결과 개수"
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value))}
            >
              {[1, 3, 5, 10].map((value) => <option key={value} value={value}>Top {value}</option>)}
            </select>
            <button type="submit" disabled={loading}>
              {loading ? "답변하는 중…" : "답변 받기"}
            </button>
          </div>
          <div className="examples" aria-label="예시 질문">
            <span>예시</span>
            {examples.map((example) => (
              <button type="button" key={example} onClick={() => search(undefined, example)}>
                {example}
              </button>
            ))}
          </div>
        </form>
        {error && <div className="error" role="alert">{error}</div>}
      </section>

      <section className="resultsSection" aria-live="polite">
        {!response && !loading && (
          <div className="emptyState">
            <span className="flask">⚗</span>
            <h2>질문을 기다리고 있어요</h2>
            <p>화학 개념, 문제 풀이, 숙제와 수업 운영 내용을 자연스럽게 물어보세요.</p>
          </div>
        )}

        {response && (
          <>
            <div className="answerPanel">
              <div className="answerTopline">
                <span className={`scopeBadge scope-${response.scope.toLowerCase()}`}>
                  {scopeLabels[response.scope]}
                </span>
                <span>확신도 {response.confidence}</span>
              </div>
              <h2>“{response.question}”</h2>
              <p className="narrativeAnswer">{response.answer}</p>
              {response.evidence_note && <p className="evidenceNote">근거 구분 · {response.evidence_note}</p>}
            </div>

            <div className="resultsHeader evidenceHeader">
              <div>
                <span className="sectionLabel">수업 근거</span>
                <h2>{response.evidence.length ? "답변에 사용한 대본" : "인용한 수업 근거 없음"}</h2>
              </div>
              <div className="metrics">
                <span><b>{response.evidence.length}</b>개 인용</span>
                <span><b>{response.retrieval.candidate_count}</b>개 후보</span>
                <span><b>{response.generation.latency_ms}</b>ms 생성</span>
              </div>
            </div>

            <div className="resultList">
              {response.evidence.map((item) => (
                <article className="resultCard" key={item.chunk_id}>
                  <div className="rank">{String(item.rank).padStart(2, "0")}</div>
                  <div className="resultBody">
                    <div className="resultMeta">
                      <span className="score">BM25 {item.score.toFixed(3)}</span>
                      <span>{item.lesson_date ?? "날짜 없음"}</span>
                      <span>청크 {item.chunk_index}</span>
                      {item.source_line_start && <span>원본 {item.source_line_start}–{item.source_line_end}줄</span>}
                    </div>
                    <p>{item.text}</p>
                    <div className="tags">
                      {item.topics.map((topic) => <span key={topic}>{topic}</span>)}
                      {item.question_numbers.map((number) => <span className="questionTag" key={number}>{number}번</span>)}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </section>

      <footer>
        <span>SQLite · FTS5 · BM25 · Gemini</span>
        <span>답변 생성 시 질문과 상위 검색 근거가 Gemini API로 전송됩니다.</span>
      </footer>
    </main>
  );
}
