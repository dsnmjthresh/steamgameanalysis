<template>
  <div class="space-y-5">
    <!-- Hero Section -->
    <section class="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
      <div class="panel p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="panel-title">
              工作台
            </p>
            <h1 class="mt-2 text-2xl font-semibold tracking-tight">
              Steam 游戏数据分析
            </h1>
            <p class="mt-1 text-sm text-muted">
              搜索游戏、查看趋势、分析评测
            </p>
          </div>
          <button
            class="button button-primary"
            :disabled="loading || loadingAlerts"
            @click="reloadReports"
          >
            <RefreshCcw :class="['h-4 w-4', loading && 'animate-spin']" />
            <span>{{ loading ? "刷新中" : "刷新" }}</span>
          </button>
        </div>

        <!-- Search -->
        <div class="mt-4 flex flex-col gap-3 md:flex-row">
          <input
            ref="searchInput"
            v-model="query"
            class="field flex-1"
            type="search"
            placeholder="搜索游戏名或 appid（如：老头环、CS2、730）"
            aria-label="搜索游戏"
            @keydown.enter="search"
            @input="onQueryChange"
          >
          <div class="flex gap-2">
            <button
              class="button button-primary md:w-28"
              :disabled="searching"
              @click="search"
            >
              <Search class="h-4 w-4" />
              <span>{{ searching ? "搜索中" : "搜索" }}</span>
            </button>
            <button
              v-if="searchResults.length > 0 || searchError"
              class="button button-ghost"
              @click="clearSearch"
            >
              <X class="h-4 w-4" />
              <span>清除</span>
            </button>
          </div>
        </div>

        <div
          v-if="searchError"
          class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
        >
          {{ searchError }}
        </div>

        <!-- Empty hint when no search performed yet -->
        <div
          v-if="!searching && !searchError && searchResults.length === 0 && !hasSearched"
          class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-8 text-sm text-muted text-center"
        >
          <Search class="h-10 w-10 mx-auto mb-3 opacity-20" />
          <p class="text-slate-300">
            输入游戏名或 AppID 开始搜索
          </p>
          <p class="mt-1">
            支持中文别名（如"老头环"→Elden Ring）、英文名、Steam AppID
          </p>
        </div>

        <!-- No results after search -->
        <div
          v-if="!searching && !searchError && searchResults.length === 0 && hasSearched"
          class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
        >
          未找到匹配的游戏。试试其他关键词或直接输入 AppID。
        </div>

        <!-- Search Results with Transition -->
        <TransitionGroup
          name="list"
          tag="div"
          class="mt-4 grid gap-2"
        >
          <article
            v-for="item in displayedResults"
            :key="item.appid"
            class="group flex items-center justify-between gap-3 rounded-lg border border-slate-700/60 bg-slate-950/60 px-3 py-3 transition hover:border-cyan-400/30 hover:bg-slate-900/90"
          >
            <button
              class="min-w-0 flex-1 text-left"
              @click="openGame(item.appid)"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-slate-100">{{ item.name }}</span>
                <span class="badge">appid {{ item.appid }}</span>
                <span
                  v-if="item.type"
                  class="badge badge-info"
                >{{ item.type }}</span>
              </div>
              <p class="mt-1 text-xs text-muted">
                置信度 {{ Math.round(item.confidence * 100) }}% · {{ item.source }}
              </p>
            </button>
            <button
              class="button icon-button button-ghost"
              :aria-label="'收藏 ' + item.name"
              @click="addFavorite(item)"
            >
              <Star
                class="h-4 w-4"
                :class="isFavorite(item.appid) ? 'fill-amber-400 text-amber-400' : ''"
              />
            </button>
          </article>
        </TransitionGroup>
        <button
          v-if="searchResults.length > 5 && !showAllResults"
          class="mt-2 button button-ghost text-sm w-full"
          @click="showAllResults = true"
        >
          显示全部 {{ searchResults.length }} 条结果
        </button>
      </div>

      <!-- Favorites + Chart -->
      <div class="space-y-4">
        <section class="panel p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="panel-title">
                关注列表
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                已保存的游戏
              </h2>
            </div>
            <span class="badge">{{ workspace.favorites.length }} / 20</span>
          </div>
          <div
            v-if="workspace.favorites.length === 0"
            class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
          >
            <Star class="h-8 w-8 mx-auto mb-2 opacity-30" />
            搜索游戏并点击 ⭐ 来关注它们。
          </div>
          <TransitionGroup
            name="list"
            tag="div"
            class="mt-4 grid gap-2 max-h-[420px] overflow-y-auto"
          >
            <article
              v-for="favorite in workspace.favorites"
              :key="favorite.appid"
              class="panel-soft p-3 transition hover:border-cyan-400/20"
            >
              <div class="flex items-start justify-between gap-2">
                <button
                  class="min-w-0 text-left"
                  @click="openGame(favorite.appid)"
                >
                  <p class="font-medium text-slate-100 text-sm truncate">
                    {{ favorite.name }}
                  </p>
                  <p class="mt-0.5 text-xs text-muted">
                    appid {{ favorite.appid }}
                  </p>
                </button>
                <div class="flex gap-1 flex-shrink-0">
                  <button
                    class="button icon-button button-ghost icon-button-sm"
                    :aria-label="'刷新 ' + favorite.name"
                    @click="refreshFavorite(favorite.appid)"
                  >
                    <RefreshCcw class="h-3.5 w-3.5" />
                  </button>
                  <button
                    class="button icon-button button-ghost button-danger icon-button-sm"
                    :aria-label="'移除 ' + favorite.name"
                    @click="workspace.removeFavorite(favorite.appid)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div
                v-if="favoriteSnapshots[favorite.appid]"
                class="mt-2 grid gap-1 text-xs text-muted grid-cols-2"
              >
                <span>在线 {{ formatNumber(favoriteSnapshots[favorite.appid]?.player_count) }}</span>
                <span>现价 {{ formatMoney(favoriteSnapshots[favorite.appid]?.final_price, favoriteSnapshots[favorite.appid]?.currency) }}</span>
              </div>
              <div
                v-else
                class="mt-2 text-xs text-muted"
              >
                <span class="skeleton skeleton-text inline-block w-24" />
              </div>
            </article>
          </TransitionGroup>
        </section>

        <section class="panel p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="panel-title">
                趋势概览
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                关注游戏当前在线人数
              </h2>
            </div>
            <span class="badge">最近快照</span>
          </div>
          <div
            v-if="chartItems.length === 0"
            class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
          >
            关注游戏后这里会显示在线人数对比图。
          </div>
          <VChart
            v-else
            class="mt-4 h-[260px] w-full"
            :option="chartOption"
            autoresize
          />
        </section>
      </div>
    </section>

    <!-- Reports + Alerts -->
    <section class="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <div class="panel p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="panel-title">
              最近报告
            </p>
            <h2 class="mt-1 text-lg font-semibold">
              本地分析输出
            </h2>
          </div>
          <span class="badge">{{ workspace.recentReports.length }} 条</span>
        </div>
        <div
          v-if="loading"
          class="mt-4 space-y-3"
        >
          <div
            v-for="i in 3"
            :key="i"
            class="skeleton skeleton-card"
          />
        </div>
        <TransitionGroup
          v-else
          name="list"
          tag="div"
          class="mt-4 grid gap-3"
        >
          <article
            v-for="report in workspace.recentReports"
            :key="report.id"
            class="panel-soft p-3"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="font-medium text-sm">
                {{ report.query }}
              </p>
              <div class="flex items-center gap-2">
                <a
                  :href="reportExportUrl(report.id, 'markdown')"
                  class="button button-ghost px-2 py-1.5 text-xs"
                >
                  <FileText class="h-3 w-3" />
                  <span>MD</span>
                </a>
                <a
                  :href="reportExportUrl(report.id, 'json')"
                  class="button button-ghost px-2 py-1.5 text-xs"
                >
                  <FileJson class="h-3 w-3" />
                  <span>JSON</span>
                </a>
                <span class="badge">{{ formatDateTime(report.created_at) }}</span>
              </div>
            </div>
            <p class="mt-2 line-clamp-3 text-sm text-muted">
              {{ report.answer_markdown }}
            </p>
          </article>
        </TransitionGroup>
      </div>

      <div class="space-y-4">
        <!-- Alerts -->
        <div class="panel p-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="panel-title">
                监控告警
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                重要变化
              </h2>
            </div>
            <span
              class="badge"
              :class="alerts.length > 0 ? 'badge-warn' : ''"
            >{{ alerts.length }} 条</span>
          </div>
          <div
            v-if="loadingAlerts"
            class="mt-4 space-y-3"
          >
            <div
              v-for="i in 2"
              :key="i"
              class="skeleton skeleton-card"
            />
          </div>
          <TransitionGroup
            v-else
            name="list"
            tag="div"
            class="mt-4 grid gap-2"
          >
            <article
              v-for="alert in alerts"
              :key="alert.id"
              class="panel-soft p-3 text-sm"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-2">
                  <AlertTriangle class="h-4 w-4 text-amber-300 flex-shrink-0" />
                  <span class="font-medium text-slate-100">appid {{ alert.appid }}</span>
                  <span class="badge">{{ alert.alert_type }}</span>
                </div>
                <span :class="['badge', alert.severity === 'high' ? 'badge-bad' : alert.severity === 'warning' ? 'badge-warn' : 'badge-ok']">
                  {{ alert.severity }}
                </span>
              </div>
              <p class="mt-2 text-slate-100">
                {{ alert.summary }}
              </p>
              <p class="mt-1 text-xs text-muted">
                {{ formatDateTime(alert.created_at) }}
              </p>
            </article>
            <div
              v-if="alerts.length === 0"
              key="empty"
              class="rounded-lg border border-dashed border-slate-700/60 p-4 text-sm text-muted text-center"
            >
              暂无告警 — 创建监控任务后这里会显示异常变化。
            </div>
          </TransitionGroup>
        </div>

        <!-- Context Panel -->
        <div class="panel p-4">
          <p class="panel-title">
            采集上下文
          </p>
          <h2 class="mt-1 text-lg font-semibold">
            当前边界
          </h2>
          <div class="mt-4 grid gap-2 text-sm text-muted">
            <div class="panel-soft flex items-center justify-between p-3">
              <span>数据范围</span>
              <span class="badge badge-ok">Steam 公开接口</span>
            </div>
            <div class="panel-soft flex items-center justify-between p-3">
              <span>存储位置</span>
              <span class="badge badge-info">本地 SQLite</span>
            </div>
            <div class="panel-soft flex items-center justify-between p-3">
              <span>外部动作</span>
              <span class="badge badge-warn">需用户确认</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { AlertTriangle, FileJson, FileText, RefreshCcw, Search, Star, Trash2, X } from "lucide-vue-next";

import { createSnapshot, listMonitorAlerts, listSnapshots, reportExportUrl, searchGames } from "@/api/client";
import type { GameCandidate, MonitorAlert, SnapshotRead } from "@/api/types";
import { formatDateTime, formatMoney, formatNumber } from "@/utils/format";
import { useWorkspaceStore } from "@/stores/workspace";

const router = useRouter();
const workspace = useWorkspaceStore();

const query = ref("");
const searchResults = ref<GameCandidate[]>([]);
const searchError = ref<string | null>(null);
const searching = ref(false);
const showAllResults = ref(false);
const hasSearched = ref(false);
const alerts = ref<MonitorAlert[]>([]);
const loading = ref(false);
const loadingAlerts = ref(false);
const favoriteSnapshots = reactive<Record<number, SnapshotRead | null>>({});
const searchInput = ref<HTMLInputElement | null>(null);

// Search debounce: auto-search on typing (≥2 chars), clear results when empty
let searchTimer: ReturnType<typeof setTimeout> | null = null;
function onQueryChange() {
  if (searchTimer) clearTimeout(searchTimer);
  const val = query.value.trim();
  if (val.length === 0) {
    // Clear immediately when input is emptied
    searchResults.value = [];
    searchError.value = null;
    hasSearched.value = false;
    showAllResults.value = false;
  } else if (val.length >= 2) {
    searchTimer = setTimeout(() => search(), 350);
  }
}

const displayedResults = computed(() =>
  showAllResults.value ? searchResults.value : searchResults.value.slice(0, 5),
);

const chartItems = computed(() =>
  workspace.favorites
    .map((favorite) => {
      const snapshot = favoriteSnapshots[favorite.appid];
      return snapshot ? { name: favorite.name, value: snapshot.player_count ?? 0 } : null;
    })
    .filter((item): item is { name: string; value: number } => Boolean(item)),
);

const chartOption = computed(() => ({
  backgroundColor: "transparent",
  grid: { left: 36, right: 18, top: 20, bottom: 30 },
  tooltip: { trigger: "axis" },
  xAxis: {
    type: "category",
    data: chartItems.value.map((item) => item.name),
    axisLabel: { color: "#94a3b8", fontSize: 11, interval: 0, rotate: chartItems.value.length > 6 ? 30 : 0 },
    axisLine: { lineStyle: { color: "rgba(95,122,183,0.2)" } },
  },
  yAxis: {
    type: "value",
    name: "在线人数",
    axisLabel: { color: "#94a3b8", formatter: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v },
    splitLine: { lineStyle: { color: "rgba(95,122,183,0.1)" } },
  },
  series: [{
    name: "在线人数",
    type: "bar",
    data: chartItems.value.map((item) => ({ value: item.value, itemStyle: { color: "#60d5ff", borderRadius: [4, 4, 0, 0] } })),
  }],
}));

function isFavorite(appid: number) { return workspace.favorites.some((f) => f.appid === appid); }

async function search() {
  const value = query.value.trim();
  if (!value) {
    searchResults.value = [];
    searchError.value = null;
    hasSearched.value = false;
    return;
  }
  if (searchTimer) clearTimeout(searchTimer);
  searching.value = true; searchError.value = null; showAllResults.value = false;
  try {
    searchResults.value = await searchGames(value);
    hasSearched.value = true;
  } catch (error) {
    searchError.value = error instanceof Error ? error.message : "搜索失败";
    searchResults.value = [];
  } finally { searching.value = false; }
}

function clearSearch() {
  query.value = "";
  searchResults.value = [];
  searchError.value = null;
  hasSearched.value = false;
  showAllResults.value = false;
  nextTick(() => searchInput.value?.focus());
}

function openGame(appid: number) { workspace.setActiveAppid(appid); void router.push({ name: "game", params: { appid } }); }
function addFavorite(game: GameCandidate) { workspace.addFavorite(game); void loadFavoriteSnapshot(game.appid); }

async function loadFavoriteSnapshot(appid: number) {
  try { const [latest] = await listSnapshots(appid, { limit: 1 }); favoriteSnapshots[appid] = latest ?? null; }
  catch { favoriteSnapshots[appid] = null; }
}

async function refreshFavorite(appid: number) { await createSnapshot(appid); await loadFavoriteSnapshot(appid); }
async function reloadReports() {
  loading.value = true; loadingAlerts.value = true;
  try { await Promise.all([workspace.loadReports(), loadAlerts()]); }
  finally { loading.value = false; loadingAlerts.value = false; }
}

async function loadAlerts() {
  try { alerts.value = await listMonitorAlerts(6); }
  finally { loadingAlerts.value = false; }
}

async function refreshFavorites() {
  await Promise.all(workspace.favorites.map((f) => loadFavoriteSnapshot(f.appid)));
}

watch(() => workspace.favorites.map((i) => i.appid).join(","), () => { void refreshFavorites(); }, { immediate: true });
onMounted(() => { void reloadReports(); });
onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer); });
</script>
