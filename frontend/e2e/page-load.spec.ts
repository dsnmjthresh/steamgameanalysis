/**
 * E2E Page-Load Smoke Tests
 *
 * Coverage:
 * - Dashboard (/) — 工作台
 * - Chat (/chat) — AI 分析助手
 * - Knowledge (/knowledge) — RAG 知识库
 * - Web Sentiment (/web-sentiment) — 网页舆情
 * - Settings (/settings) — 设置
 * - Compare (/compare) — 对比
 *
 * All API calls are mocked via page.route() — no real backend, Steam API, or LLM.
 */

import { test, expect } from "@playwright/test";
import { setupApiMocks } from "./fixtures/mock-api";

// ── Helpers ───────────────────────────────────────────────────────────────

/** Navigate to a path with API mocks pre-installed */
async function gotoWithMocks(page: import("@playwright/test").Page, path: string) {
  await setupApiMocks(page);
  await page.goto(path, { waitUntil: "networkidle" });
}

// ── Dashboard ─────────────────────────────────────────────────────────────

test.describe("Dashboard page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.locator("h1")).toContainText("Steam 游戏数据分析");
    await expect(page).toHaveTitle(/工作台/);
  });

  test("shows search input", async ({ page }) => {
    await gotoWithMocks(page, "/");

    const searchInput = page.locator('input[aria-label="搜索游戏"]');
    await expect(searchInput).toBeVisible();
  });

  test("shows favorites section", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.getByText("已保存的游戏")).toBeVisible();
  });

  test("shows reports section", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.getByText("最近报告")).toBeVisible();
  });

  test("shows monitor alerts section", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.getByText("监控告警")).toBeVisible();
  });

  test("shows context panel", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.getByText("采集上下文")).toBeVisible();
  });

  test("no error message visible", async ({ page }) => {
    await gotoWithMocks(page, "/");

    // The search error area should not exist unless a search fails
    await expect(page.locator(".text-rose-200")).toHaveCount(0);
  });

  test("nav bar health indicator shows API online", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await expect(page.getByText("API 在线")).toBeVisible({ timeout: 5000 });
  });
});

// ── Chat ──────────────────────────────────────────────────────────────────

test.describe("Chat page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await expect(page.locator("h1")).toContainText("AI 分析助手");
    await expect(page).toHaveTitle(/聊天/);
  });

  test("shows chat input", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    const chatInput = page.locator('input[aria-label="聊天输入"]');
    await expect(chatInput).toBeVisible();
  });

  test("shows send button", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await expect(page.getByText("发送")).toBeVisible();
  });

  test("shows conversation sidebar", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await expect(page.getByText("当前对话")).toBeVisible();
  });

  test("shows history reports section", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await expect(page.getByText("历史报告")).toBeVisible();
  });

  test("shows read-only mode toggle", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await expect(page.getByText("只读模式，不采集新数据")).toBeVisible();
  });
});

// ── Knowledge ─────────────────────────────────────────────────────────────

test.describe("Knowledge page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/knowledge");

    await expect(page.locator("h1")).toContainText("RAG 知识库管理");
    await expect(page).toHaveTitle(/知识库/);
  });

  test("shows document stats badges", async ({ page }) => {
    await gotoWithMocks(page, "/knowledge");

    // Stats badges for documents, chunks, and vector backend
    await expect(page.getByText("文档 3")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("分块 42")).toBeVisible({ timeout: 5000 });
  });

  test("shows upload form", async ({ page }) => {
    await gotoWithMocks(page, "/knowledge");

    await expect(page.getByText("上传文档")).toBeVisible();
    await expect(page.getByPlaceholder("文档标题")).toBeVisible();
    await expect(page.getByPlaceholder("文档内容（Markdown 格式）...")).toBeVisible();
  });

  test("shows document list section", async ({ page }) => {
    await gotoWithMocks(page, "/knowledge");

    await expect(page.getByText("文档列表")).toBeVisible();
  });

  test("shows search test section", async ({ page }) => {
    await gotoWithMocks(page, "/knowledge");

    await expect(page.getByRole("heading", { name: "检索测试" })).toBeVisible();
  });
});

// ── Web Sentiment ─────────────────────────────────────────────────────────

test.describe("Web Sentiment page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/web-sentiment");

    await expect(page.locator("h1")).toContainText("历史分析浏览");
    await expect(page).toHaveTitle(/网页舆情/);
  });

  test("shows timeline / sources toggle", async ({ page }) => {
    await gotoWithMocks(page, "/web-sentiment");

    await expect(page.getByText("时间线")).toBeVisible();
    await expect(page.getByText("来源")).toBeVisible();
  });

  test("shows filter bar", async ({ page }) => {
    await gotoWithMocks(page, "/web-sentiment");

    await expect(page.getByPlaceholder("游戏名过滤...")).toBeVisible();
    await expect(page.getByPlaceholder("appid 过滤")).toBeVisible();
  });

  test("shows export JSON button", async ({ page }) => {
    await gotoWithMocks(page, "/web-sentiment");

    await expect(page.getByText("导出 JSON")).toBeVisible();
  });

  test("shows sentiment events from mock data", async ({ page }) => {
    await gotoWithMocks(page, "/web-sentiment");

    await expect(page.getByText("Counter-Strike 2")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Elden Ring", { exact: true })).toBeVisible({ timeout: 5000 });
  });
});

// ── Settings ──────────────────────────────────────────────────────────────

test.describe("Settings page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.locator("h1")).toContainText("地区、语言与模型");
    await expect(page).toHaveTitle(/设置/);
  });

  test("shows save button", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByRole("button", { name: "保存" })).toBeVisible();
  });

  test("shows default query settings", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByText("默认查询")).toBeVisible();
  });

  test("shows model & collection settings", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByText("模型与采集")).toBeVisible();
  });

  test("shows key status section", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByText("密钥状态")).toBeVisible();
    await expect(page.getByText("已配置 ✓").first()).toBeVisible({ timeout: 5000 });
  });

  test("shows region presets", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByText("CN / CNY / 简中")).toBeVisible();
    await expect(page.getByText("US / USD / English")).toBeVisible();
  });

  test("shows auth token section", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByText("身份验证")).toBeVisible();
  });

  test("shows collapsible management sections", async ({ page }) => {
    await gotoWithMocks(page, "/settings");

    await expect(page.getByRole("heading", { name: "定时采集" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "游戏别名管理" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "研究文档" })).toBeVisible();
  });
});

// ── Compare ───────────────────────────────────────────────────────────────

test.describe("Compare page", () => {
  test("loads and shows main heading", async ({ page }) => {
    await gotoWithMocks(page, "/compare");

    await expect(page.locator("h1")).toContainText("比较游戏或快照");
    await expect(page).toHaveTitle(/对比/);
  });
});

// ── Navigation ────────────────────────────────────────────────────────────

test.describe("App navigation", () => {
  test("nav links exist for all main routes", async ({ page }) => {
    await gotoWithMocks(page, "/");

    const nav = page.locator('nav[aria-label="主导航"]');
    await expect(nav.getByText("工作台")).toBeVisible();
    await expect(nav.getByText("对比")).toBeVisible();
    await expect(nav.getByText("聊天")).toBeVisible();
    await expect(nav.getByText("知识库")).toBeVisible();
    await expect(nav.getByText("舆情")).toBeVisible();
    await expect(nav.getByText("设置")).toBeVisible();
  });

  test("can navigate from dashboard to chat via nav link", async ({ page }) => {
    await gotoWithMocks(page, "/");

    // Re-install mocks before navigation (page context might reset on SPA nav)
    await page.locator('nav[aria-label="主导航"]').getByText("聊天").click();
    await page.waitForURL("/chat");
    await expect(page.locator("h1")).toContainText("AI 分析助手");
  });

  test("can navigate from dashboard to settings via nav link", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await page.locator('nav[aria-label="主导航"]').getByText("设置").click();
    await page.waitForURL("/settings");
    await expect(page.locator("h1")).toContainText("地区、语言与模型");
  });

  test("can navigate from dashboard to knowledge via nav link", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await page.locator('nav[aria-label="主导航"]').getByText("知识库").click();
    await page.waitForURL("/knowledge");
    await expect(page.locator("h1")).toContainText("RAG 知识库管理");
  });

  test("can navigate from dashboard to web-sentiment via nav link", async ({ page }) => {
    await gotoWithMocks(page, "/");

    await page.locator('nav[aria-label="主导航"]').getByText("舆情").click();
    await page.waitForURL("/web-sentiment");
    await expect(page.locator("h1")).toContainText("历史分析浏览");
  });

  test("logo links back to dashboard", async ({ page }) => {
    await gotoWithMocks(page, "/chat");

    await page.locator('a:has-text("SteamAnalysis")').click();
    await page.waitForURL("/");
    await expect(page.locator("h1")).toContainText("Steam 游戏数据分析");
  });
});
