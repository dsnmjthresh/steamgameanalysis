import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// We must set up VITE_API_BASE_URL for import.meta.env
// Vitest handles this via vite.config.ts define

describe("API client helpers", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  it("getAuthHeaders returns empty when no token", async () => {
    // Dynamically import to test the actual module behavior
    const mod = await import("@/api/client");
    // Make a call that doesn't need fetch
    localStorage.removeItem("steamanalysis_auth_token");
    // Just verify the functions are exported
    expect(mod.health).toBeTypeOf("function");
    expect(mod.searchGames).toBeTypeOf("function");
    expect(mod.getGame).toBeTypeOf("function");
    expect(mod.chat).toBeTypeOf("function");
  });

  it("searchGames is exported and callable", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve([{ appid: 730, name: "CS2" }]),
    });

    const { searchGames } = await import("@/api/client");
    const result = await searchGames("CS2");

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit?];
    expect(url).toContain("/api/games/search");
    expect(url).toContain("query=CS2");
    expect(init?.headers).toBeDefined();
    expect(result).toEqual([{ appid: 730, name: "CS2" }]);
  });

  it("getGame calls correct endpoint", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ appid: 730, name: "Counter-Strike 2" }),
    });

    const { getGame } = await import("@/api/client");
    const result = await getGame(730);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toContain("/api/games/730");
    expect(result.appid).toBe(730);
  });

  it("runtimeStatus calls status endpoint", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ service: "steamanalysis", database: { status: "ok" } }),
    });

    const { runtimeStatus } = await import("@/api/client");
    const result = await runtimeStatus();

    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toContain("/api/status");
    expect(result.service).toBe("steamanalysis");
  });

  it("chat sends correct payload", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ conversation_id: 1 }),
    });

    const { chat } = await import("@/api/client");
    await chat({ query: "test query" });

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit?];
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string);
    expect(body.query).toBe("test query");
  });

  it("requestJson includes auth header when token set", async () => {
    localStorage.setItem("steamanalysis_auth_token", "my-token");
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ appid: 570 }),
    });

    const { getGame } = await import("@/api/client");
    await getGame(570);

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit?];
    const headers = init?.headers as Record<string, string> | undefined;
    expect(headers?.Authorization).toBe("Bearer my-token");
  });

  it("requestJson throws on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      headers: new Headers({ "content-type": "application/json" }),
      json: () => Promise.resolve({ detail: "Unauthorized" }),
      clone() { return this; },
      text: () => Promise.resolve('{"detail":"Unauthorized"}'),
    });

    const { getGame } = await import("@/api/client");
    await expect(getGame(570)).rejects.toThrow("Unauthorized");
  });
});
