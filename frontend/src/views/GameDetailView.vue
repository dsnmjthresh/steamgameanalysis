<template>
  <div class="space-y-5">
    <!-- Header -->
    <section class="panel overflow-hidden">
      <div
        v-if="game?.header_image"
        class="relative h-44 md:h-52 overflow-hidden"
      >
        <img
          :src="game.header_image"
          :alt="game.name"
          class="h-full w-full object-cover"
          loading="lazy"
        >
        <div class="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/35 to-transparent" />
      </div>
      <div class="p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p class="panel-title">
              游戏详情
            </p>
            <h1 class="mt-2 text-2xl font-semibold tracking-tight">
              {{ game?.name ?? `appid ${appid}` }}
            </h1>
            <p class="mt-2 text-sm text-muted">
              appid {{ appid }} · {{ game?.type ?? "未知类型" }} ·
              {{ latestSnapshot ? formatDateTime(latestSnapshot.collected_at) : "暂无快照" }}
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              class="button"
              @click="loadAll"
            >
              <RefreshCcw class="h-4 w-4" />
              <span>加载</span>
            </button>
            <button
              class="button button-primary"
              :disabled="refreshing"
              @click="refreshSnapshot"
            >
              <Download class="h-4 w-4" />
              <span>{{ refreshing ? "采集中" : "采集快照" }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Metric Cards -->
    <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard
        label="在线人数"
        :value="formatNumber(latestSnapshot?.player_count)"
        :hint="latestHint"
        :icon="Users"
      />
      <MetricCard
        label="现价"
        :value="formatMoney(latestSnapshot?.final_price, latestSnapshot?.currency)"
        :hint="priceHint"
        :icon="Wallet"
      />
      <MetricCard
        label="折扣"
        :value="formatPercent(latestSnapshot?.discount_percent)"
        :hint="discountHint"
        :icon="Tag"
      />
      <MetricCard
        label="推荐总数"
        :value="formatNumber(latestSnapshot?.recommendations_total)"
        :hint="'来自 Steam'"
        :icon="Sparkles"
      />
    </section>

    <!-- Chart + Timeline (collapsible) -->
    <section class="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <div class="panel p-4">
        <div
          class="collapsible-header"
          @click="toggleSection('chart')"
        >
          <div>
            <p class="panel-title">
              历史快照
            </p>
            <h2 class="mt-1 text-lg font-semibold">
              时间线 · {{ snapshots.length }} 条
            </h2>
          </div>
          <div class="flex items-center gap-2">
            <div class="flex flex-wrap gap-1">
              <button
                v-for="label in quickLabels"
                :key="label"
                class="button button-ghost px-2 py-1 text-xs"
                @click.stop="labelLatest(label)"
              >
                <Tag class="h-3 w-3" />
                <span>{{ label }}</span>
              </button>
            </div>
            <ChevronDown
              class="h-4 w-4 text-muted transition-transform"
              :class="collapsedSections.chart ? 'rotate-180' : ''"
            />
          </div>
        </div>

        <div
          v-if="snapshots.length === 0 && !chartLoading"
          class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
        >
          暂无快照 — 点击"采集快照"按钮来获取数据。
        </div>
        <div
          v-if="chartLoading"
          class="mt-4 skeleton skeleton-chart"
        />

        <div
          :class="['collapsible-content', collapsedSections.chart ? 'collapsed' : '']"
          :style="{ maxHeight: collapsedSections.chart ? '0px' : '800px' }"
        >
          <VChart
            v-if="snapshots.length > 0"
            class="mt-4 h-[300px] w-full"
            :option="chartOption"
            autoresize
          />

          <!-- Snapshot List -->
          <div class="mt-4 grid gap-2 max-h-[400px] overflow-y-auto">
            <TransitionGroup name="list">
              <article
                v-for="snapshot in visibleSnapshots"
                :key="snapshot.id"
                class="panel-soft p-3 text-sm"
              >
                <div class="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p class="font-medium text-slate-100">
                      {{ formatDateTime(snapshot.collected_at) }}
                    </p>
                    <p class="mt-1 text-xs text-muted">
                      在线 {{ formatNumber(snapshot.player_count) }} · 现价 {{ formatMoney(snapshot.final_price, snapshot.currency) }} · 折扣 {{ formatPercent(snapshot.discount_percent) }}
                    </p>
                  </div>
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="label in snapshot.labels"
                      :key="label"
                      class="badge badge-info text-xs"
                    >{{ label }}</span>
                  </div>
                </div>
              </article>
            </TransitionGroup>
          </div>
          <button
            v-if="snapshots.length > snapshotPageSize && !showAllSnapshots"
            class="mt-3 button button-ghost text-sm w-full"
            @click="showAllSnapshots = true"
          >
            显示全部 {{ snapshots.length }} 条快照
          </button>
        </div>
      </div>

      <!-- News + Sources -->
      <div class="space-y-4">
        <section class="panel p-4">
          <div
            class="collapsible-header"
            @click="toggleSection('news')"
          >
            <div>
              <p class="panel-title">
                新闻
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                Steam 新闻 · {{ latestSnapshot?.news.length ?? 0 }} 条
              </h2>
            </div>
            <ChevronDown
              class="h-4 w-4 text-muted transition-transform"
              :class="collapsedSections.news ? 'rotate-180' : ''"
            />
          </div>
          <div
            :class="['collapsible-content', collapsedSections.news ? 'collapsed' : '']"
            :style="{ maxHeight: collapsedSections.news ? '0px' : '600px' }"
          >
            <div
              v-if="latestSnapshot?.news.length"
              class="mt-4 grid gap-2 max-h-[500px] overflow-y-auto"
            >
              <article
                v-for="item in latestSnapshot.news.slice(0, 15)"
                :key="item.title"
                class="panel-soft p-3 text-sm"
              >
                <div class="flex items-start justify-between gap-2">
                  <div>
                    <p class="font-medium text-slate-100 line-clamp-2">
                      {{ item.title }}
                    </p>
                    <p class="mt-1 text-xs text-muted">
                      {{ formatDateTime(item.published_at) }}
                    </p>
                  </div>
                  <a
                    v-if="item.url"
                    :href="item.url"
                    target="_blank"
                    rel="noreferrer"
                    class="button icon-button button-ghost icon-button-sm flex-shrink-0"
                    aria-label="打开新闻链接"
                  >
                    <ExternalLink class="h-3.5 w-3.5" />
                  </a>
                </div>
                <p
                  v-if="item.summary"
                  class="mt-2 text-muted line-clamp-2"
                >
                  {{ item.summary }}
                </p>
              </article>
            </div>
            <div
              v-else
              class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-4 text-sm text-muted text-center"
            >
              暂无新闻。
            </div>
          </div>
        </section>

        <section class="panel p-4">
          <p class="panel-title">
            数据来源
          </p>
          <h2 class="mt-1 text-lg font-semibold">
            采集 URL
          </h2>
          <div class="mt-4 grid gap-1 text-sm">
            <a
              v-for="(url, key) in latestSnapshot?.source_urls ?? {}"
              :key="key"
              :href="url"
              target="_blank"
              rel="noreferrer"
              class="panel-soft flex items-center justify-between gap-2 px-3 py-2 text-muted transition hover:border-cyan-400/30 hover:text-slate-100"
            >
              <span>{{ key }}</span>
              <ExternalLink class="h-3 w-3 flex-shrink-0" />
            </a>
          </div>
        </section>
      </div>
    </section>

    <!-- Trend + Prices (collapsible) -->
    <section class="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <ReviewPanel :appid="appid" />

      <div class="space-y-4">
        <!-- Trend Analysis -->
        <section class="panel p-4">
          <div
            class="collapsible-header"
            @click="toggleSection('trend')"
          >
            <div>
              <p class="panel-title">
                趋势分析
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                {{ trend ? `最近 ${trend.days} 天` : '趋势解读' }}
              </h2>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="button button-ghost px-2 py-1 text-xs"
                :disabled="trendLoading"
                @click.stop="loadTrend"
              >
                <LineChart class="h-3.5 w-3.5" />
                <span>{{ trendLoading ? "分析中" : "刷新" }}</span>
              </button>
              <ChevronDown
                class="h-4 w-4 text-muted transition-transform"
                :class="collapsedSections.trend ? 'rotate-180' : ''"
              />
            </div>
          </div>

          <div
            v-if="trendError"
            class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
          >
            {{ trendError }}
          </div>
          <div
            v-else-if="trendLoading"
            class="mt-4 skeleton skeleton-card"
          />
          <div
            v-else-if="trend"
            :class="['collapsible-content', collapsedSections.trend ? 'collapsed' : '']"
            :style="{ maxHeight: collapsedSections.trend ? '0px' : '800px' }"
          >
            <div class="mt-4 space-y-3">
              <div class="panel-soft p-3">
                <p class="text-sm leading-7 text-slate-100">
                  {{ trend.summary }}
                </p>
              </div>
              <div class="grid gap-2 grid-cols-3">
                <div class="panel-soft p-3 text-center">
                  <p class="text-xs text-muted">
                    快照数
                  </p>
                  <p class="mt-1 text-lg font-semibold">
                    {{ formatNumber(trend.snapshot_count) }}
                  </p>
                </div>
                <div class="panel-soft p-3 text-center">
                  <p class="text-xs text-muted">
                    峰值
                  </p>
                  <p class="mt-1 text-lg font-semibold">
                    {{ formatNumber(trend.player_count_peak) }}
                  </p>
                </div>
                <div class="panel-soft p-3 text-center">
                  <p class="text-xs text-muted">
                    均值
                  </p>
                  <p class="mt-1 text-lg font-semibold">
                    {{ formatNumber(trend.player_count_avg) }}
                  </p>
                </div>
              </div>
              <div class="panel-soft p-3">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs text-muted">趋势</span>
                  <span :class="['badge', trend.player_count_trend === '上升趋势' ? 'badge-ok' : trend.player_count_trend === '下降趋势' ? 'badge-bad' : 'badge-warn']">{{ trend.player_count_trend }}</span>
                </div>
                <p class="mt-2 text-sm text-slate-100">
                  {{ trend.recommendation ?? "暂无建议" }}
                </p>
              </div>
              <div v-if="trend.price_changes.length > 0">
                <p class="panel-title mb-2">
                  价格变化
                </p>
                <div class="grid gap-1 max-h-[200px] overflow-y-auto">
                  <article
                    v-for="item in trend.price_changes"
                    :key="item.snapshot_id"
                    class="panel-soft p-2 text-sm"
                  >
                    <p class="text-xs text-muted">
                      {{ formatDateTime(item.collected_at) }}
                    </p>
                    <p class="mt-1">
                      {{ formatMoney(item.previous_price, item.currency) }} → <span class="text-amber-300">{{ formatMoney(item.current_price, item.currency) }}</span>
                    </p>
                  </article>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Regional Prices -->
        <section class="panel p-4">
          <div
            class="collapsible-header"
            @click="toggleSection('prices')"
          >
            <div>
              <p class="panel-title">
                多地区价格
              </p>
              <h2 class="mt-1 text-lg font-semibold">
                CN / US / JP
              </h2>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="button button-ghost px-2 py-1 text-xs"
                :disabled="priceLoading"
                @click.stop="loadRegionalPrices"
              >
                <Globe2 class="h-3.5 w-3.5" />
                <span>{{ priceLoading ? "加载中" : "刷新" }}</span>
              </button>
              <ChevronDown
                class="h-4 w-4 text-muted transition-transform"
                :class="collapsedSections.prices ? 'rotate-180' : ''"
              />
            </div>
          </div>

          <div
            v-if="priceError"
            class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
          >
            {{ priceError }}
          </div>
          <div
            v-else-if="priceLoading"
            class="mt-4 skeleton skeleton-card"
          />
          <div
            v-else
            :class="['collapsible-content', collapsedSections.prices ? 'collapsed' : '']"
            :style="{ maxHeight: collapsedSections.prices ? '0px' : '500px' }"
          >
            <div
              v-if="regionalPrices.length"
              class="mt-4 grid gap-2"
            >
              <article
                v-for="region in regionalPrices"
                :key="`${region.price?.cc}-${region.price?.language}`"
                class="panel-soft p-3"
              >
                <div class="flex items-center justify-between gap-2">
                  <div>
                    <p class="font-medium text-slate-100">
                      {{ region.price?.cc ?? "地区" }} / {{ region.price?.currency ?? "N/A" }}
                    </p>
                    <p class="text-xs text-muted">
                      {{ region.price?.language ?? "default" }}
                    </p>
                  </div>
                  <span :class="['badge', (region.price?.discount_percent ?? 0) > 0 ? 'badge-warn' : '']">{{ formatPercent(region.price?.discount_percent) }}</span>
                </div>
                <p class="mt-2 text-lg font-semibold">
                  {{ region.price?.is_free ? "免费" : formatMoney(region.price?.final_price, region.price?.currency) }}
                </p>
              </article>
            </div>
            <div
              v-else
              class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-4 text-sm text-muted text-center"
            >
              点击刷新获取多地区价格。
            </div>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ChevronDown, Download, ExternalLink, Globe2, LineChart, RefreshCcw, Sparkles, Tag, Users, Wallet } from "lucide-vue-next";
import { createSnapshot, getGame, getTrendAnalysis, labelSnapshot, listSnapshots, priceComparison } from "@/api/client";
import type { GameDetail, GameRead, SnapshotRead, TrendAnalysis } from "@/api/types";
import MetricCard from "@/components/MetricCard.vue";
import ReviewPanel from "@/components/ReviewPanel.vue";
import { formatDateTime, formatMoney, formatNumber, formatPercent, formatShortDate } from "@/utils/format";

const route = useRoute();
const appid = computed(() => Number(route.params.appid));

const game = ref<GameRead | null>(null);
const snapshots = ref<SnapshotRead[]>([]);
const trend = ref<TrendAnalysis | null>(null);
const regionalPrices = ref<GameDetail[]>([]);
const refreshing = ref(false);
const trendLoading = ref(false);
const trendError = ref<string | null>(null);
const priceLoading = ref(false);
const priceError = ref<string | null>(null);
const chartLoading = ref(true);
const showAllSnapshots = ref(false);
const snapshotPageSize = 12;

// Collapsible sections — all open by default
const collapsedSections = reactive<Record<string, boolean>>({
  chart: false, news: false, trend: false, prices: false,
});
const quickLabels = ["A", "B", "促销前", "促销后"];

const latestSnapshot = computed(() => snapshots.value[0] ?? null);
const visibleSnapshots = computed(() => showAllSnapshots.value ? snapshots.value : snapshots.value.slice(0, snapshotPageSize));

const latestHint = computed(() => latestSnapshot.value ? `采集于 ${formatDateTime(latestSnapshot.value.collected_at)}` : "刷新后显示");
const priceHint = computed(() => latestSnapshot.value?.currency ? `币种 ${latestSnapshot.value.currency}` : "无价格数据");
const discountHint = computed(() => latestSnapshot.value?.discount_percent ? `采集于 ${formatShortDate(latestSnapshot.value.collected_at)}` : "未检测到折扣");

const chartOption = computed(() => {
  const data = snapshots.value.slice().reverse();
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#94a3b8", fontSize: 11 } },
    grid: { left: 42, right: 20, top: 36, bottom: 32 },
    xAxis: {
      type: "category",
      data: data.map((s) => new Date(s.collected_at).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit" })),
      axisLabel: { color: "#94a3b8", fontSize: 10, interval: Math.max(1, Math.floor(data.length / 12)) },
      axisLine: { lineStyle: { color: "rgba(95,122,183,0.2)" } },
    },
    yAxis: [{
      type: "value", name: "在线人数",
      axisLabel: { color: "#94a3b8", formatter: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v },
      splitLine: { lineStyle: { color: "rgba(95,122,183,0.1)" } },
    }],
    series: [{
      name: "在线人数", type: "line", smooth: true,
      data: data.map((s) => s.player_count ?? 0),
      itemStyle: { color: "#60d5ff" }, lineStyle: { color: "#60d5ff", width: 2 },
      areaStyle: { color: "rgba(96, 213, 255, 0.1)" },
    }],
  };
});

function toggleSection(key: string) { collapsedSections[key] = !collapsedSections[key]; }

async function loadTrend() {
  if (!Number.isFinite(appid.value)) return;
  trendLoading.value = true; trendError.value = null;
  try { trend.value = await getTrendAnalysis(appid.value, 7); }
  catch (cause) { trend.value = null; trendError.value = cause instanceof Error ? cause.message : "读取趋势分析失败"; }
  finally { trendLoading.value = false; }
}

async function loadRegionalPrices() {
  if (!Number.isFinite(appid.value)) return;
  priceLoading.value = true; priceError.value = null;
  try { regionalPrices.value = await priceComparison(appid.value); }
  catch (cause) { regionalPrices.value = []; priceError.value = cause instanceof Error ? cause.message : "读取多地区价格失败"; }
  finally { priceLoading.value = false; }
}

async function loadAll() {
  if (!Number.isFinite(appid.value)) return;
  chartLoading.value = true;
  const currentAppid = appid.value;
  try {
    const [gameData, snapshotData] = await Promise.all([
      getGame(currentAppid),
      listSnapshots(currentAppid, { limit: 50 }),
    ]);
    game.value = gameData;
    snapshots.value = snapshotData;
    await Promise.all([loadTrend(), loadRegionalPrices()]);
  } finally { chartLoading.value = false; }
}

async function refreshSnapshot() {
  if (!Number.isFinite(appid.value)) return;
  refreshing.value = true;
  try { await createSnapshot(appid.value); await loadAll(); }
  finally { refreshing.value = false; }
}

async function labelLatest(label: string) {
  const current = latestSnapshot.value;
  if (!current) return;
  await labelSnapshot(current.id, { label });
  await loadAll();
}

watch(() => route.params.appid, () => { void loadAll(); }, { immediate: true });
</script>
