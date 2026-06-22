<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Download, ExternalLink, Filter, Table2, Clock } from "lucide-vue-next";
import { listSentimentEvents, listWebSources } from "@/api/client";
import type { SentimentEventRead, WebSourceRead } from "@/api/types";

// ---- Filters ----
const filterGame = ref("");
const filterAppid = ref<number | null>(null);
const viewMode = ref<"timeline" | "sources">("timeline");

// ---- Events ----
const events = ref<SentimentEventRead[]>([]);
const loadingEvents = ref(false);

async function loadEvents() {
  loadingEvents.value = true;
  try {
    events.value = await listSentimentEvents({
      game: filterGame.value || null,
      appid: filterAppid.value ?? null,
      limit: 50,
    });
  } catch {
    events.value = [];
  } finally {
    loadingEvents.value = false;
  }
}

// ---- Sources ----
const sources = ref<WebSourceRead[]>([]);
const loadingSources = ref(false);

async function loadSources() {
  loadingSources.value = true;
  try {
    sources.value = await listWebSources({
      game: filterGame.value || null,
      appid: filterAppid.value ?? null,
      limit: 50,
    });
  } catch {
    sources.value = [];
  } finally {
    loadingSources.value = false;
  }
}

async function handleFilter() {
  if (viewMode.value === "timeline") {
    await loadEvents();
  } else {
    await loadSources();
  }
}

function sentimentClass(sentiment: string) {
  const map: Record<string, string> = {
    positive: "bg-emerald-500/20 text-emerald-400",
    negative: "bg-rose-500/20 text-rose-400",
    mixed: "bg-amber-500/20 text-amber-400",
    neutral: "bg-slate-500/20 text-slate-400",
  };
  return map[sentiment] ?? "bg-slate-500/20 text-slate-400";
}

function severityClass(severity: string) {
  const map: Record<string, string> = {
    low: "badge",
    medium: "badge badge-warn",
    high: "badge bg-orange-500/20 text-orange-400",
    critical: "badge bg-red-500/20 text-red-400",
  };
  return map[severity] ?? "badge";
}

function exportEvents() {
  const blob = new Blob([JSON.stringify(events.value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `web-sentiment-export-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

onMounted(() => {
  loadEvents();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <section class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="panel-title">
            网页舆情
          </p>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">
            历史分析浏览
          </h1>
          <p class="mt-1 text-sm text-muted">
            浏览、过滤和导出网页舆情分析结果
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            class="button button-ghost text-xs"
            :class="{ '!border-cyan-400/40 !bg-cyan-400/10': viewMode === 'timeline' }"
            @click="viewMode = 'timeline'; loadEvents()"
          >
            <Clock class="h-3.5 w-3.5" />
            时间线
          </button>
          <button
            class="button button-ghost text-xs"
            :class="{ '!border-cyan-400/40 !bg-cyan-400/10': viewMode === 'sources' }"
            @click="viewMode = 'sources'; loadSources()"
          >
            <Table2 class="h-3.5 w-3.5" />
            来源
          </button>
          <button
            class="button button-ghost text-xs"
            :disabled="events.length === 0"
            @click="exportEvents"
          >
            <Download class="h-3.5 w-3.5" />
            导出 JSON
          </button>
        </div>
      </div>

      <!-- Filter Bar -->
      <div class="mt-4 grid gap-3 md:grid-cols-[1fr_0.35fr_auto]">
        <input
          v-model="filterGame"
          class="field"
          placeholder="游戏名过滤..."
          @keyup.enter="handleFilter"
        >
        <input
          v-model.number="filterAppid"
          class="field"
          type="number"
          min="1"
          placeholder="appid 过滤"
          @keyup.enter="handleFilter"
        >
        <button
          class="button button-ghost"
          @click="handleFilter"
        >
          <Filter class="h-3.5 w-3.5" />
          筛选
        </button>
      </div>
    </section>

    <!-- Timeline View -->
    <div
      v-if="viewMode === 'timeline'"
      class="grid gap-3"
    >
      <div
        v-if="loadingEvents"
        class="space-y-2"
      >
        <div
          v-for="i in 3"
          :key="i"
          class="skeleton skeleton-text"
        />
      </div>
      <article
        v-for="event in events"
        :key="event.id"
        class="panel-soft p-4"
      >
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-semibold">{{ event.game_key }}</span>
              <span
                v-if="event.appid"
                class="badge text-xs"
              >appid {{ event.appid }}</span>
              <span :class="['badge text-xs', sentimentClass(event.sentiment)]">{{ event.sentiment }}</span>
              <span :class="['badge text-xs', severityClass(event.severity)]">{{ event.severity }}</span>
            </div>
            <p class="mt-1 text-sm">
              {{ event.summary }}
            </p>
          </div>
          <div class="text-xs text-muted text-right shrink-0">
            <div>{{ event.event_date ? new Date(event.event_date).toLocaleDateString("zh-CN") : "" }}</div>
            <div class="mt-1">
              证据 {{ event.evidence_count }} 条
            </div>
            <div>置信度 {{ (event.confidence * 100).toFixed(0) }}%</div>
          </div>
        </div>
      </article>
      <div
        v-if="events.length === 0 && !loadingEvents"
        class="text-sm text-muted text-center py-8"
      >
        暂无舆情事件。请先通过 Chat 或 API 运行 web_sentiment 分析。
      </div>
    </div>

    <!-- Sources View -->
    <div
      v-if="viewMode === 'sources'"
      class="grid gap-3"
    >
      <div
        v-if="loadingSources"
        class="space-y-2"
      >
        <div
          v-for="i in 3"
          :key="i"
          class="skeleton skeleton-text"
        />
      </div>
      <article
        v-for="source in sources"
        :key="source.id"
        class="panel-soft p-4"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="badge text-xs">{{ source.source_type }}</span>
              <span
                v-if="source.appid"
                class="badge text-xs"
              >appid {{ source.appid }}</span>
              <span class="text-xs text-muted">{{ new Date(source.fetched_at).toLocaleDateString("zh-CN") }}</span>
            </div>
            <a
              v-if="source.source_url"
              :href="source.source_url"
              target="_blank"
              rel="noreferrer"
              class="mt-1 text-sm font-medium text-cyan-300 hover:text-cyan-200 inline-flex items-center gap-1"
            >
              {{ source.title || source.source_url }}
              <ExternalLink class="h-3 w-3" />
            </a>
            <p class="mt-1 text-xs text-muted line-clamp-2">
              {{ source.excerpt }}
            </p>
          </div>
        </div>
      </article>
      <div
        v-if="sources.length === 0 && !loadingSources"
        class="text-sm text-muted text-center py-8"
      >
        暂无来源记录。
      </div>
    </div>
  </div>
</template>
