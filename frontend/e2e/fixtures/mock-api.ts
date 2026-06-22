/**
 * E2E API Mock Helpers
 *
 * All routes intercept the real API base URL (http://127.0.0.1:9000/api/**)
 * and return deterministic mock responses so tests never hit a real backend,
 * Steam API, or LLM.
 */

import type { Page } from "@playwright/test";

// ── Mock response factories ──────────────────────────────────────────────

export function healthResponse() {
  return { status: "ok", service: "steamanalysis" };
}

export function settingsResponse() {
  return {
    default_cc: "CN",
    default_language: "schinese",
    default_currency: "CNY",
    deepseek_model: "deepseek-v4-pro",
    allow_model_fallback: true,
    collection_interval_minutes: 60,
    deepseek_api_key: true,
    steam_api_key: true,
    firecrawl_api_key: false,
  };
}

export function reportsResponse() {
  return [
    {
      id: 1,
      query: "CS2 最近30天在线人数趋势如何",
      answer_markdown:
        "根据最近30天的快照数据，CS2 的平均在线人数为 **892,341**，峰值为 **1,234,567**。整体趋势平稳，周末有明显峰值。",
      created_at: "2026-06-08T12:00:00Z",
      snapshot_ids: [101, 102, 103],
      model: "deepseek-v4-pro",
      prompt_version: "v3",
      tool_versions: null,
    },
    {
      id: 2,
      query: "Elden Ring 最新折扣信息",
      answer_markdown:
        "Elden Ring 目前在 Steam 国区的最终价格为 ¥298，折扣力度为 **30%**，原价 ¥428。该折扣从 6 月 5 日开始，预计持续至 6 月 15 日。",
      created_at: "2026-06-07T09:30:00Z",
      snapshot_ids: [201],
      model: null,
      prompt_version: null,
      tool_versions: null,
    },
  ];
}

export function monitorAlertsResponse() {
  return [
    {
      id: 1,
      appid: 730,
      snapshot_id: 101,
      alert_type: "player_count_drop",
      summary: "CS2 在线人数在过去 24 小时内下降了 15%，从 892,341 降至 758,490。",
      severity: "warning",
      created_at: "2026-06-09T08:00:00Z",
    },
  ];
}

export function knowledgeStatsResponse() {
  return {
    documents: 3,
    chunks: 42,
    fts_enabled: true,
    sqlite_vec_enabled: false,
    embedding_dim: 768,
    chunking_policy: "markdown_heading",
  };
}

export function knowledgeDocumentsResponse() {
  return [
    {
      id: 1,
      title: "CS2 更新日志 2026-06",
      source_type: "patch_note",
      source_uri: null,
      appid: 730,
      tags: ["cs2", "update"],
      metadata: {},
      content_hash: "abc123",
      chunk_count: 15,
      created_at: "2026-06-05T10:00:00Z",
      updated_at: "2026-06-05T10:00:00Z",
    },
    {
      id: 2,
      title: "Steam 夏季特卖趋势分析",
      source_type: "report",
      source_uri: null,
      appid: null,
      tags: ["sale", "trends"],
      metadata: {},
      content_hash: "def456",
      chunk_count: 20,
      created_at: "2026-06-03T14:00:00Z",
      updated_at: "2026-06-03T14:00:00Z",
    },
  ];
}

export function sentimentEventsResponse() {
  return [
    {
      id: 1,
      game_key: "Counter-Strike 2",
      appid: 730,
      event_date: "2026-06-08",
      event_type: "community_sentiment",
      summary: "Reddit 社区对 CS2 最新更新的整体评价偏正面，玩家普遍认可新的反作弊措施。",
      sentiment: "positive",
      severity: "low",
      evidence_count: 12,
      confidence: 0.85,
      created_at: "2026-06-08T18:00:00Z",
      metadata: {},
    },
    {
      id: 2,
      game_key: "Elden Ring",
      appid: 1245620,
      event_date: "2026-06-07",
      event_type: "price_change_discussion",
      summary: "微博和贴吧讨论 Elden Ring 折扣，部分玩家认为折扣力度不足。",
      sentiment: "mixed",
      severity: "low",
      evidence_count: 8,
      confidence: 0.72,
      created_at: "2026-06-07T20:00:00Z",
      metadata: {},
    },
  ];
}

// ── Route handler ────────────────────────────────────────────────────────

/**
 * Install mock API routes on the given page.
 * Must be called before page.goto() so routes are in place before Vue
 * components fire their onMounted API calls.
 */
export async function setupApiMocks(page: Page) {
  // Catch-all: intercept every fetch to the backend API base URL.
  // The Vite define replaces import.meta.env.VITE_API_BASE_URL with
  // "http://127.0.0.1:9000/api", so all client.ts requests go there.
  await page.route("http://127.0.0.1:9000/api/**", (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();

    // ── GET /api/health ──
    if (path === "/api/health" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(healthResponse()),
      });
    }

    // ── GET /api/settings ──
    if (path === "/api/settings" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(settingsResponse()),
      });
    }

    // ── PUT /api/settings ──
    if (path === "/api/settings" && method === "PUT") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(settingsResponse()),
      });
    }

    // ── GET /api/reports?limit=N ──
    if (path === "/api/reports" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(reportsResponse()),
      });
    }

    // ── GET /api/monitors/alerts?limit=N ──
    if (path === "/api/monitors/alerts" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(monitorAlertsResponse()),
      });
    }

    // ── GET /api/knowledge/stats ──
    if (path === "/api/knowledge/stats" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(knowledgeStatsResponse()),
      });
    }

    // ── GET /api/knowledge/documents?limit=N ──
    if (path === "/api/knowledge/documents" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(knowledgeDocumentsResponse()),
      });
    }

    // ── GET /api/web-sentiment/events?... ──
    if (path === "/api/web-sentiment/events" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sentimentEventsResponse()),
      });
    }

    // ── GET /api/games/{appid}/snapshots?... ──
    const snapshotsMatch = path.match(/^\/api\/games\/(\d+)\/snapshots$/);
    if (snapshotsMatch && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }

    // ── GET /api/aliases/games?... ──
    if (path === "/api/aliases/games" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }

    // ── GET /api/monitors ──
    if (path === "/api/monitors" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    }

    // ── Fallback: return empty/404 for unhandled API paths ──
    console.warn(`[mock-api] Unhandled route: ${method} ${path}`);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });
}
