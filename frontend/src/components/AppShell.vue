<template>
  <div class="app-shell">
    <header class="sticky top-0 z-30 border-b border-slate-800/90 bg-slate-950/88 backdrop-blur">
      <div class="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-4 py-3">
        <RouterLink
          to="/"
          class="flex items-center gap-2 font-semibold text-cyan-300 hover:text-cyan-200 transition-colors"
        >
          <Gamepad2 class="h-5 w-5" />
          <span class="hidden sm:inline">SteamAnalysis</span>
          <span class="sm:hidden">SA</span>
        </RouterLink>
        <nav
          class="flex flex-wrap items-center gap-0.5"
          aria-label="主导航"
        >
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="button button-ghost px-3 py-2 text-sm"
            :class="{ '!border-cyan-400/40 !bg-cyan-400/10 !text-cyan-200': route.path === item.to }"
            :aria-current="route.path === item.to ? 'page' : undefined"
          >
            <component
              :is="item.icon"
              class="h-4 w-4"
            />
            <span class="hidden sm:inline">{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="flex items-center gap-2">
          <span
            :class="['badge text-xs', healthState === 'ok' ? 'badge-ok' : healthState === 'error' ? 'badge-bad' : 'badge-warn']"
            :title="healthLabel"
          >
            <span
              class="h-2 w-2 rounded-full"
              :class="healthDotClass"
            />
            <span class="hidden sm:inline">{{ healthLabel }}</span>
          </span>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-[1600px] px-4 py-5">
      <slot />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, RouterLink } from "vue-router";
import { BookOpen, Gamepad2, GitCompareArrows, Globe, LayoutDashboard, MessageSquareText, Settings2 } from "lucide-vue-next";

import { health } from "@/api/client";
import { useSettingsStore } from "@/stores/settings";
import { useWorkspaceStore } from "@/stores/workspace";

const route = useRoute();
const settingsStore = useSettingsStore();
const workspaceStore = useWorkspaceStore();

const healthState = ref<"checking" | "ok" | "error">("checking");

const navItems = [
  { to: "/", label: "工作台", icon: LayoutDashboard },
  { to: "/compare", label: "对比", icon: GitCompareArrows },
  { to: "/chat", label: "聊天", icon: MessageSquareText },
  { to: "/knowledge", label: "知识库", icon: BookOpen },
  { to: "/web-sentiment", label: "舆情", icon: Globe },
  { to: "/settings", label: "设置", icon: Settings2 },
];

const healthLabel = computed(() =>
  healthState.value === "ok" ? "API 在线" : healthState.value === "error" ? "API 失联" : "连接中",
);
const healthDotClass = computed(() =>
  healthState.value === "ok" ? "bg-emerald-400" : healthState.value === "error" ? "bg-rose-400" : "bg-amber-400 animate-pulse",
);

// Update document.title on route change
watch(() => route.path, (path) => {
  const titles: Record<string, string> = {
    "/": "工作台",
    "/compare": "对比",
    "/chat": "聊天",
    "/knowledge": "知识库",
    "/web-sentiment": "网页舆情",
    "/settings": "设置",
  };
  const suffix = titles[path] ? ` — ${titles[path]}` : "";
  document.title = `SteamAnalysis${suffix}`;
  if (path.startsWith("/games/")) {
    document.title = "SteamAnalysis — 游戏详情";
  }
}, { immediate: true });

onMounted(async () => {
  workspaceStore.hydrate();
  if (!settingsStore.data) {
    await settingsStore.load();
  }
  try {
    await health();
    healthState.value = "ok";
  } catch {
    healthState.value = "error";
  }
});
</script>
