<template>
  <div class="space-y-5">
    <section class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="panel-title">
            A / B 对比
          </p>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">
            比较游戏或快照
          </h1>
          <p class="mt-1 text-sm text-muted">
            输入两组 appid + 快照 ID（或标签）来对比指标
          </p>
        </div>
        <button
          class="button button-primary"
          :disabled="loading"
          @click="runCompare"
        >
          <GitCompareArrows class="h-4 w-4" />
          <span>{{ loading ? "对比中" : "开始对比" }}</span>
        </button>
      </div>

      <div class="mt-5 grid gap-4 lg:grid-cols-2">
        <section
          class="panel-soft p-4"
          :class="left.appid ? 'border-l-2 border-l-cyan-400/30' : ''"
        >
          <p class="panel-title">
            🔵 左侧（A）
          </p>
          <div class="mt-3 grid gap-3">
            <label class="grid gap-1 text-xs text-muted">
              AppID <span class="text-rose-400">*</span>
              <input
                v-model="left.appid"
                class="field"
                type="number"
                placeholder="如 730"
                aria-label="左侧 AppID"
              >
            </label>
            <label class="grid gap-1 text-xs text-muted">
              快照 ID <span class="text-muted">（可选）</span>
              <input
                v-model="left.snapshot_id"
                class="field"
                type="number"
                placeholder="不填则取最新"
              >
            </label>
            <label class="grid gap-1 text-xs text-muted">
              标签筛选 <span class="text-muted">（可选）</span>
              <input
                v-model="left.label"
                class="field"
                placeholder="如：促销前"
              >
            </label>
          </div>
          <div class="mt-2 flex flex-wrap gap-1">
            <button
              v-for="f in workspace.favorites.slice(0, 5)"
              :key="'l'+f.appid"
              class="button button-ghost px-2 py-1 text-xs"
              @click="left.appid = String(f.appid)"
            >
              {{ f.name }}
            </button>
          </div>
        </section>

        <section
          class="panel-soft p-4"
          :class="right.appid ? 'border-l-2 border-l-amber-400/30' : ''"
        >
          <p class="panel-title">
            🟠 右侧（B）
          </p>
          <div class="mt-3 grid gap-3">
            <label class="grid gap-1 text-xs text-muted">
              AppID <span class="text-rose-400">*</span>
              <input
                v-model="right.appid"
                class="field"
                type="number"
                placeholder="如 570"
                aria-label="右侧 AppID"
              >
            </label>
            <label class="grid gap-1 text-xs text-muted">
              快照 ID <span class="text-muted">（可选）</span>
              <input
                v-model="right.snapshot_id"
                class="field"
                type="number"
                placeholder="不填则取最新"
              >
            </label>
            <label class="grid gap-1 text-xs text-muted">
              标签筛选 <span class="text-muted">（可选）</span>
              <input
                v-model="right.label"
                class="field"
                placeholder="如：促销后"
              >
            </label>
          </div>
          <div class="mt-2 flex flex-wrap gap-1">
            <button
              v-for="f in workspace.favorites.slice(0, 5)"
              :key="'r'+f.appid"
              class="button button-ghost px-2 py-1 text-xs"
              @click="right.appid = String(f.appid)"
            >
              {{ f.name }}
            </button>
          </div>
        </section>
      </div>

      <!-- Quick presets -->
      <div class="mt-3 flex flex-wrap gap-2 text-xs">
        <button
          class="button button-ghost px-2 py-1"
          @click="presetCompare(730, 570)"
        >
          CS2 vs Dota 2
        </button>
        <button
          class="button button-ghost px-2 py-1"
          @click="presetCompare(1245620, 2358720)"
        >
          艾尔登法环 vs 黑神话
        </button>
      </div>

      <div
        v-if="error"
        class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
      >
        {{ error }}
      </div>
    </section>

    <!-- Results -->
    <section
      v-if="result"
      class="grid gap-4 xl:grid-cols-[1fr_0.9fr]"
    >
      <div class="panel p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="panel-title">
              对比结果
            </p>
            <h2 class="mt-1 text-lg font-semibold">
              {{ result.left_appid }} vs {{ result.right_appid }}
            </h2>
          </div>
          <span class="badge">快照 {{ result.left_snapshot_id }} vs {{ result.right_snapshot_id }}</span>
        </div>
        <p class="mt-4 text-sm leading-7 text-slate-100">
          {{ result.summary }}
        </p>

        <div class="mt-4 grid gap-2">
          <article
            v-for="metric in result.metrics"
            :key="metric.field"
            class="panel-soft p-3 text-sm"
          >
            <div class="flex items-center justify-between gap-2">
              <p class="font-medium">
                {{ metric.field }}
              </p>
              <span :class="['badge text-xs', metric.comparable ? 'badge-ok' : 'badge-warn']">{{ metric.comparable ? "可比" : "不可比" }}</span>
            </div>
            <div class="mt-2 grid gap-1 text-xs text-muted grid-cols-3">
              <div>A: {{ metric.left ?? "—" }}</div>
              <div>B: {{ metric.right ?? "—" }}</div>
              <div :class="metric.delta != null && metric.delta !== 0 ? ((metric.delta ?? 0) > 0 ? 'text-green-400' : 'text-rose-400') : ''">
                Δ: {{ metric.delta ?? "—" }}
              </div>
            </div>
            <p
              v-if="metric.note"
              class="mt-2 text-xs text-amber-200"
            >
              {{ metric.note }}
            </p>
          </article>
        </div>
      </div>

      <div class="space-y-4">
        <section class="panel p-4">
          <p class="panel-title">
            可比性
          </p>
          <div class="mt-3 grid gap-2 text-sm">
            <div class="panel-soft flex items-center justify-between px-3 py-2">
              <span>地区</span>
              <span :class="['badge', result.comparable_region ? 'badge-ok' : 'badge-warn']">{{ result.comparable_region ? "一致" : "不一致" }}</span>
            </div>
            <div class="panel-soft flex items-center justify-between px-3 py-2">
              <span>币种</span>
              <span :class="['badge', result.comparable_currency ? 'badge-ok' : 'badge-warn']">{{ result.comparable_currency ? "一致" : "不一致" }}</span>
            </div>
          </div>
        </section>

        <section class="panel p-4">
          <p class="panel-title">
            不确定项
          </p>
          <ul class="mt-3 grid gap-1 text-sm text-muted">
            <li
              v-for="item in result.uncertainties"
              :key="item"
              class="panel-soft px-3 py-2"
            >
              ⚠ {{ item }}
            </li>
            <li
              v-if="result.uncertainties.length === 0"
              class="panel-soft px-3 py-2 text-center"
            >
              暂无。
            </li>
          </ul>
        </section>

        <section class="panel p-4">
          <p class="panel-title">
            辅助图
          </p>
          <VChart
            v-if="chartOption"
            class="mt-3 h-[240px] w-full"
            :option="chartOption"
            autoresize
          />
        </section>
      </div>
    </section>

    <!-- Empty state -->
    <section
      v-if="!result && !loading && !error"
      class="panel p-6 text-center text-muted"
    >
      <GitCompareArrows class="h-12 w-12 mx-auto mb-3 opacity-20" />
      <p class="text-lg text-slate-300">
        选择两个游戏或快照开始对比
      </p>
      <p class="mt-2 text-sm">
        输入 AppID + 快照信息后点击"开始对比"
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { GitCompareArrows } from "lucide-vue-next";
import { compareSnapshots } from "@/api/client";
import type { ComparisonResult } from "@/api/types";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();

const left = reactive<{ appid: string; snapshot_id: string; label: string }>({ appid: "", snapshot_id: "", label: "" });
const right = reactive<{ appid: string; snapshot_id: string; label: string }>({ appid: "", snapshot_id: "", label: "" });
const loading = ref(false);
const error = ref<string | null>(null);
const result = ref<ComparisonResult | null>(null);

if (workspace.favorites[0]) left.appid = String(workspace.favorites[0].appid);
if (workspace.favorites[1]) right.appid = String(workspace.favorites[1].appid);

function presetCompare(a: number, b: number) { left.appid = String(a); right.appid = String(b); void runCompare(); }

const chartOption = computed(() => {
  if (!result.value) return null;
  const playerMetric = result.value.metrics.find((m) => m.field === "player_count");
  const priceMetric = result.value.metrics.find((m) => m.field === "final_price");
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#94a3b8", fontSize: 11 } },
    grid: { left: 42, right: 20, top: 36, bottom: 28 },
    xAxis: { type: "category", data: ["A", "B"], axisLabel: { color: "#94a3b8" } },
    yAxis: [{ type: "value", axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "rgba(95,122,183,0.1)" } } }],
    series: [
      { name: "在线人数", type: "bar", data: [playerMetric?.left ?? 0, playerMetric?.right ?? 0], itemStyle: { color: "#60d5ff", borderRadius: [4, 4, 0, 0] } },
      { name: "现价", type: "bar", data: [priceMetric?.left ?? 0, priceMetric?.right ?? 0], itemStyle: { color: "#f5b84d", borderRadius: [4, 4, 0, 0] } },
    ],
  };
});

function targetPayload(source: typeof left) {
  return { snapshot_id: source.snapshot_id ? Number(source.snapshot_id) : null, appid: source.appid ? Number(source.appid) : null, label: source.label.trim() || null };
}

async function runCompare() {
  if (!left.appid || !right.appid) { error.value = "请为两侧都输入 AppID"; return; }
  loading.value = true; error.value = null; result.value = null;
  try { result.value = await compareSnapshots({ left: targetPayload(left), right: targetPayload(right) }); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "对比失败"; }
  finally { loading.value = false; }
}

workspace.$subscribe(() => {
  if (!left.appid && workspace.favorites[0]) left.appid = String(workspace.favorites[0].appid);
  if (!right.appid && workspace.favorites[1]) right.appid = String(workspace.favorites[1].appid);
});
</script>
