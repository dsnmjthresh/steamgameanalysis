import { defineStore } from "pinia";

import { getSettings as fetchSettings, updateSettings as saveSettings } from "@/api/client";
import type { AppSettingsRead, AppSettingsUpdate } from "@/api/types";

export const useSettingsStore = defineStore("settings", {
  state: () => ({
    data: null as AppSettingsRead | null,
    loading: false,
    saving: false,
    error: null as string | null,
    authToken: (localStorage.getItem("steamanalysis_auth_token") ?? "") as string,
  }),
  actions: {
    setAuthToken(token: string) {
      this.authToken = token;
      localStorage.setItem("steamanalysis_auth_token", token);
    },
    async load() {
      this.loading = true;
      this.error = null;
      try {
        this.data = await fetchSettings();
      } catch (error) {
        this.error = error instanceof Error ? error.message : "加载设置失败";
      } finally {
        this.loading = false;
      }
    },
    async save(payload: AppSettingsUpdate) {
      this.saving = true;
      this.error = null;
      try {
        this.data = await saveSettings(payload);
        return this.data;
      } catch (error) {
        this.error = error instanceof Error ? error.message : "保存设置失败";
        throw error;
      } finally {
        this.saving = false;
      }
    },
  },
});
