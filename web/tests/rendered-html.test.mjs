import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the chemistry search interface", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="ko">/i);
  assert.match(html, /<title>화학 수업 챗봇<\/title>/i);
  assert.match(html, /수업에서 배운 내용을/);
  assert.match(html, /답변 받기/);
  assert.match(html, /SQLite · FTS5 · BM25 · Gemini/);
  assert.match(html, /질문과 상위 검색 근거가 Gemini API로 전송됩니다/);
  assert.doesNotMatch(html, /Starter Project|react-loading-skeleton/);
});

test("chat UI calls only the local answer API", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /http:\/\/127\.0\.0\.1:8765\/api\/answer/);
  assert.match(page, /JSON\.stringify\(\{ question: searchText, top_k: topK \}\)/);
  assert.match(page, /aria-label="검색 결과 개수"/);
  assert.match(page, /aria-live="polite"/);
  assert.match(layout, /lang="ko"/);
  assert.match(layout, /title:\s*"화학 수업 챗봇"/);
  assert.match(packageJson, /"name": "chemistry-class-chatbot"/);
  assert.doesNotMatch(page, /https:\/\//);
});
