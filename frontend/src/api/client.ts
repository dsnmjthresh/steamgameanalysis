import type {
  AgentAnalysisResult,
  AppSettingsRead,
  AppSettingsUpdate,
  ChatRequest,
  ChatResponse,
  ChatStreamEvent,
  ComparisonResult,
  GameAliasCreate,
  GameAliasRead,
  GameCandidate,
  GameDetail,
  GameRead,
  HealthResponse,
  KnowledgeDocumentCreate,
  KnowledgeDocumentRead,
  KnowledgeIndexStats,
  KnowledgeSearchResponse,
  MonitorAlert,
  MonitorTask,
  MonitorTaskCreate,
  ReportRead,
  RuntimeStatus,
  SentimentAnalysisResult,
  SentimentEventRead,
  SnapshotCreateRequest,
  SnapshotLabelCreate,
  SnapshotRead,
  TaskRead,
  TrendAnalysis,
  WebSentimentReport,
  WebSourceRead,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:9000/api";

function buildPath(path: string, query?: Record<string, string | number | boolean | null | undefined>) {
  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, String(value));
      }
    }
  }
  const queryString = params.toString();
  return queryString ? `${path}?${queryString}` : path;
}

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("steamanalysis_auth_token") ?? import.meta.env.VITE_AUTH_TOKEN ?? "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function readErrorMessage(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";
  try {
    const text = await response.clone().text();
    if (contentType.includes("application/json")) {
      try {
        const payload = JSON.parse(text) as { detail?: unknown; message?: unknown };
        if (typeof payload.detail === "string") {
          return payload.detail;
        }
        if (typeof payload.message === "string") {
          return payload.message;
        }
      } catch {
        // Ignore JSON parsing failures and fall back to plain text.
      }
    }
    return text || `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

export function health() {
  return requestJson<HealthResponse>("/health");
}

export function runtimeStatus() {
  return requestJson<RuntimeStatus>("/status");
}

export function searchGames(query: string, cc?: string, language?: string) {
  return requestJson<GameCandidate[]>(buildPath("/games/search", { query, cc, language }));
}

export function listGameAliases(query?: string, limit = 100) {
  return requestJson<GameAliasRead[]>(buildPath("/aliases/games", { query, limit }));
}

export function createGameAlias(payload: GameAliasCreate) {
  return requestJson<GameAliasRead>("/aliases/games", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteGameAlias(id: number) {
  return requestJson<void>(`/aliases/games/${id}`, { method: "DELETE" });
}

export function listKnowledgeDocuments(limit = 50) {
  return requestJson<KnowledgeDocumentRead[]>(buildPath("/knowledge/documents", { limit }));
}

export function createKnowledgeDocument(payload: KnowledgeDocumentCreate) {
  return requestJson<KnowledgeDocumentRead>("/knowledge/documents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteKnowledgeDocument(id: number) {
  return requestJson<void>(`/knowledge/documents/${id}`, { method: "DELETE" });
}

export function searchKnowledge(query: string, params: { appid?: number | null; limit?: number } = {}) {
  return requestJson<KnowledgeSearchResponse>("/knowledge/search", {
    method: "POST",
    body: JSON.stringify({ query, appid: params.appid, limit: params.limit ?? 6 }),
  });
}

export function getKnowledgeStats() {
  return requestJson<KnowledgeIndexStats>("/knowledge/stats");
}

export function analyzeWebSentiment(payload: {
  query: string;
  game?: string | null;
  appid?: number | null;
  event_date?: string | null;
  limit?: number;
  persist_to_knowledge?: boolean;
}) {
  return requestJson<WebSentimentReport>("/web-sentiment/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getGame(appid: number) {
  return requestJson<GameRead>(`/games/${appid}`);
}

export function priceComparison(appid: number, region: string[] = ["CN:schinese", "US:english", "JP:japanese"]) {
  const params = new URLSearchParams();
  for (const item of region) {
    params.append("region", item);
  }
  return requestJson<GameDetail[]>(`/games/${appid}/price-comparison?${params.toString()}`);
}

export function createSnapshot(appid: number, payload: SnapshotCreateRequest = {}) {
  return requestJson<SnapshotRead>(`/games/${appid}/snapshots`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listSnapshots(
  appid: number,
  params: { limit?: number; label?: string; start?: string | null; end?: string | null } = {},
) {
  return requestJson<SnapshotRead[]>(buildPath(`/games/${appid}/snapshots`, params));
}

export function labelSnapshot(snapshotId: number, payload: SnapshotLabelCreate) {
  return requestJson(`/snapshots/${snapshotId}/labels`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function compareSnapshots(payload: {
  left: { snapshot_id?: number | null; appid?: number | null; label?: string | null };
  right: { snapshot_id?: number | null; appid?: number | null; label?: string | null };
}) {
  return requestJson<ComparisonResult>("/compare", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function chat(payload: ChatRequest) {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getReviewAnalysis(appid: number) {
  return requestJson<SentimentAnalysisResult>(`/games/${appid}/reviews`);
}

export function analyzeReviews(appid: number, count = 20, language = "schinese") {
  return requestJson<SentimentAnalysisResult>(
    buildPath(`/games/${appid}/reviews/analyze`, { count, language }),
    { method: "POST" },
  );
}

export function getTrendAnalysis(appid: number, days = 7) {
  return requestJson<TrendAnalysis>(buildPath(`/games/${appid}/trend`, { days }));
}

export function listMonitors() {
  return requestJson<MonitorTask[]>("/monitors");
}

export function createMonitor(payload: MonitorTaskCreate) {
  return requestJson<MonitorTask>("/monitors", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteMonitor(id: number) {
  return requestJson<void>(`/monitors/${id}`, { method: "DELETE" });
}

export function listMonitorAlerts(limit = 20) {
  return requestJson<MonitorAlert[]>(buildPath("/monitors/alerts", { limit }));
}

export async function streamChat(
  payload: ChatRequest,
  onEvent?: (event: ChatStreamEvent) => void,
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  if (!response.body) {
    throw new Error("流式响应没有可读取的内容");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: ChatResponse | null = null;

  function consumeBlock(block: string) {
    const lines = block.split("\n");
    const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
    const dataLine = lines.find((line) => line.startsWith("data:"));
    const rawData = dataLine?.slice(5).trim();
    const data = rawData ? JSON.parse(rawData) as Record<string, unknown> : {};
    onEvent?.({ event: eventName, data });
    if (eventName === "result") {
      finalResponse = data as unknown as ChatResponse;
    }
    if (eventName === "error") {
      throw new Error(typeof data.message === "string" ? data.message : "流式请求失败");
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block) {
        consumeBlock(block);
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      break;
    }
  }

  if (!finalResponse) {
    throw new Error("流式响应没有返回最终结果");
  }
  return finalResponse;
}

export function listReports(limit = 20) {
  return requestJson<ReportRead[]>(`/reports?limit=${limit}`);
}

export function reportExportUrl(reportId: number, format: "markdown" | "json") {
  return `${API_BASE_URL}/reports/${reportId}/export/${format}`;
}

export function getSettings() {
  return requestJson<AppSettingsRead>("/settings");
}

export function updateSettings(payload: AppSettingsUpdate) {
  return requestJson<AppSettingsRead>("/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

// ---- Task Queue ----

export function createTask(payload: { task_type: string; input_data: Record<string, unknown>; user_key?: string | null }) {
  return requestJson<TaskRead>("/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getTask(taskId: number) {
  return requestJson<TaskRead>(`/tasks/${taskId}`);
}

export function cancelTask(taskId: number) {
  return requestJson<TaskRead>(`/tasks/${taskId}/cancel`, { method: "POST" });
}

export function listTasks(params: { status?: string; task_type?: string; limit?: number } = {}) {
  return requestJson<TaskRead[]>(buildPath("/tasks", params));
}

// ---- Web Sentiment History ----

export function listSentimentEvents(params: { game?: string | null; appid?: number | null; limit?: number } = {}) {
  return requestJson<SentimentEventRead[]>(buildPath("/web-sentiment/events", params));
}

export function listWebSources(params: { game?: string | null; appid?: number | null; limit?: number } = {}) {
  return requestJson<WebSourceRead[]>(buildPath("/web-sentiment/sources", params));
}

export function agentResultFromChat(response: ChatResponse): AgentAnalysisResult {
  return response.result;
}
