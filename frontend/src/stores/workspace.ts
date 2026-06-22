import { defineStore } from "pinia";

import { listReports } from "@/api/client";
import type { GameCandidate, ReportRead } from "@/api/types";

export interface FavoriteGame {
  appid: number;
  name: string;
  type?: string | null;
  header_image?: string | null;
}

const FAVORITES_KEY = "steamanalysis:favorites";

function readFavorites(): FavoriteGame[] {
  if (typeof localStorage === "undefined") {
    return [];
  }
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return raw ? (JSON.parse(raw) as FavoriteGame[]) : [];
  } catch {
    return [];
  }
}

function writeFavorites(favorites: FavoriteGame[]) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites));
}

export const useWorkspaceStore = defineStore("workspace", {
  state: () => ({
    favorites: [] as FavoriteGame[],
    recentReports: [] as ReportRead[],
    activeAppid: null as number | null,
    loadingReports: false,
  }),
  getters: {
    hasFavorite: (state) => (appid: number) => state.favorites.some((game) => game.appid === appid),
  },
  actions: {
    hydrate() {
      this.favorites = readFavorites();
    },
    addFavorite(game: FavoriteGame | GameCandidate) {
      const next = {
        appid: game.appid,
        name: game.name,
        type: game.type ?? null,
        header_image: "header_image" in game ? game.header_image ?? null : null,
      };
      const filtered = this.favorites.filter((item) => item.appid !== next.appid);
      this.favorites = [next, ...filtered].slice(0, 20);
      writeFavorites(this.favorites);
    },
    removeFavorite(appid: number) {
      this.favorites = this.favorites.filter((game) => game.appid !== appid);
      writeFavorites(this.favorites);
    },
    setActiveAppid(appid: number | null) {
      this.activeAppid = appid;
    },
    async loadReports() {
      this.loadingReports = true;
      try {
        this.recentReports = await listReports(8);
      } finally {
        this.loadingReports = false;
      }
    },
  },
});
