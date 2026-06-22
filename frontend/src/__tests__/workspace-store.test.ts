import { describe, it, expect, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useWorkspaceStore } from "@/stores/workspace";
import type { FavoriteGame } from "@/stores/workspace";

function makeGame(overrides: Partial<FavoriteGame> = {}): FavoriteGame {
  return {
    appid: 730,
    name: "CS2",
    type: "game",
    header_image: null,
    ...overrides,
  };
}

describe("workspaceStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
  });

  it("starts with empty favorites", () => {
    const store = useWorkspaceStore();
    expect(store.favorites).toHaveLength(0);
  });

  it("hydrate loads favorites from localStorage", () => {
    localStorage.setItem(
      "steamanalysis:favorites",
      JSON.stringify([makeGame({ appid: 730 }), makeGame({ appid: 570, name: "Dota 2" })]),
    );
    const store = useWorkspaceStore();
    store.hydrate();
    expect(store.favorites).toHaveLength(2);
    expect(store.favorites[0].appid).toBe(730);
    expect(store.favorites[1].name).toBe("Dota 2");
  });

  it("hydrate handles corrupt localStorage gracefully", () => {
    localStorage.setItem("steamanalysis:favorites", "{broken json");
    const store = useWorkspaceStore();
    store.hydrate();
    expect(store.favorites).toHaveLength(0);
  });

  it("addFavorite adds a game and limits to 20", () => {
    const store = useWorkspaceStore();
    for (let i = 0; i < 25; i++) {
      store.addFavorite(makeGame({ appid: i, name: `Game${i}` }));
    }
    expect(store.favorites).toHaveLength(20);
    // newest first
    expect(store.favorites[0].appid).toBe(24);
    expect(store.favorites[19].appid).toBe(5);
  });

  it("addFavorite dedupes existing appid", () => {
    const store = useWorkspaceStore();
    store.addFavorite(makeGame({ appid: 730, name: "CS2" }));
    store.addFavorite(makeGame({ appid: 730, name: "CS2 Updated" }));
    expect(store.favorites).toHaveLength(1);
    expect(store.favorites[0].name).toBe("CS2 Updated");
  });

  it("removeFavorite removes by appid", () => {
    const store = useWorkspaceStore();
    store.addFavorite(makeGame({ appid: 730 }));
    store.addFavorite(makeGame({ appid: 570, name: "Dota 2" }));
    store.removeFavorite(730);
    expect(store.favorites).toHaveLength(1);
    expect(store.favorites[0].appid).toBe(570);
  });

  it("removeFavorite is no-op for unknown appid", () => {
    const store = useWorkspaceStore();
    store.addFavorite(makeGame({ appid: 730 }));
    store.removeFavorite(99999);
    expect(store.favorites).toHaveLength(1);
  });

  it("hasFavorite getter works", () => {
    const store = useWorkspaceStore();
    store.addFavorite(makeGame({ appid: 730 }));
    expect(store.hasFavorite(730)).toBe(true);
    expect(store.hasFavorite(570)).toBe(false);
  });

  it("setActiveAppid updates state", () => {
    const store = useWorkspaceStore();
    store.setActiveAppid(730);
    expect(store.activeAppid).toBe(730);
    store.setActiveAppid(null);
    expect(store.activeAppid).toBeNull();
  });
});
