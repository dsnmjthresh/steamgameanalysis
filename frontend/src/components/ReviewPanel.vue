<template>
  <section class="panel p-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <p class="panel-title">
          评论分析
        </p>
        <h2 class="mt-2 text-lg font-semibold">
          最近 Steam 评论抽样
        </h2>
      </div>
      <button
        class="button button-primary"
        :disabled="running"
        @click="runAnalysis"
      >
        <MessageSquareText class="h-4 w-4" />
        <span>{{ running ? "分析中" : "重新分析" }}</span>
      </button>
    </div>

    <div
      v-if="loading"
      class="mt-4 text-sm text-muted"
    >
      正在读取评论分析...
    </div>

    <div
      v-else-if="analysis"
      class="mt-4 space-y-4"
    >
      <div class="grid gap-3 md:grid-cols-3">
        <div class="panel-soft p-3">
          <p class="text-xs text-muted">
            样本数
          </p>
          <p class="mt-2 text-xl font-semibold">
            {{ formatNumber(analysis.total_reviews) }}
          </p>
        </div>
        <div class="panel-soft p-3">
          <p class="text-xs text-muted">
            样本好评率
          </p>
          <p class="mt-2 text-xl font-semibold">
            {{ formatPercent(Math.round(analysis.positive_ratio * 100)) }}
          </p>
        </div>
        <div class="panel-soft p-3">
          <p class="text-xs text-muted">
            分析时间
          </p>
          <p class="mt-2 text-sm font-medium">
            {{ formatDateTime(analysis.analyzed_at) }}
          </p>
        </div>
      </div>

      <div class="grid gap-4 xl:grid-cols-2">
        <div class="panel-soft p-3">
          <p class="text-xs text-muted">
            玩家主要夸
          </p>
          <div class="mt-3 flex flex-wrap gap-2">
            <span
              v-for="item in analysis.top_praise_keywords"
              :key="item"
              class="badge badge-ok"
            >{{ item }}</span>
            <span
              v-if="analysis.top_praise_keywords.length === 0"
              class="text-sm text-muted"
            >暂无稳定关键词</span>
          </div>
        </div>
        <div class="panel-soft p-3">
          <p class="text-xs text-muted">
            玩家主要吐槽
          </p>
          <div class="mt-3 flex flex-wrap gap-2">
            <span
              v-for="item in analysis.top_complaint_keywords"
              :key="item"
              class="badge badge-warn"
            >{{ item }}</span>
            <span
              v-if="analysis.top_complaint_keywords.length === 0"
              class="text-sm text-muted"
            >暂无稳定关键词</span>
          </div>
        </div>
      </div>

      <div class="panel-soft p-3">
        <p class="text-xs text-muted">
          摘要
        </p>
        <p class="mt-2 text-sm leading-7 text-slate-100">
          {{ analysis.summary }}
        </p>
        <a
          v-if="analysis.source_url"
          :href="analysis.source_url"
          target="_blank"
          rel="noreferrer"
          class="mt-3 inline-flex items-center gap-1 text-xs text-cyan-300"
        >
          <ExternalLink class="h-3.5 w-3.5" />
          <span>打开评论来源</span>
        </a>
      </div>

      <div
        v-if="analysis.reviews.length"
        class="grid gap-3"
      >
        <p class="panel-title">
          评论样本
        </p>
        <article
          v-for="review in analysis.reviews.slice(0, 3)"
          :key="review.review_id"
          class="panel-soft p-3"
        >
          <div class="flex items-center justify-between gap-2 text-xs text-muted">
            <span :class="['badge', review.voted_up ? 'badge-ok' : 'badge-warn']">
              {{ review.voted_up ? "好评" : "差评" }}
            </span>
            <span>{{ formatDateTime(review.timestamp_created) }}</span>
          </div>
          <p class="mt-3 line-clamp-4 text-sm leading-7 text-slate-100">
            {{ review.review_text }}
          </p>
        </article>
      </div>
    </div>

    <div
      v-else
      class="mt-4 rounded-lg border border-dashed border-slate-700/60 p-4 text-sm text-muted"
    >
      暂无评论分析结果。点击上方按钮即可抽样分析最近评论。
    </div>

    <div
      v-if="error"
      class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
    >
      {{ error }}
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { ExternalLink, MessageSquareText } from "lucide-vue-next";

import { analyzeReviews, getReviewAnalysis } from "@/api/client";
import type { SentimentAnalysisResult } from "@/api/types";
import { formatDateTime, formatNumber, formatPercent } from "@/utils/format";

const props = defineProps<{
  appid: number;
}>();

const analysis = ref<SentimentAnalysisResult | null>(null);
const loading = ref(false);
const running = ref(false);
const error = ref<string | null>(null);

async function loadLatest() {
  if (!Number.isFinite(props.appid)) {
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    analysis.value = await getReviewAnalysis(props.appid);
  } catch (cause) {
    analysis.value = null;
    if (cause instanceof Error && /not found|404/i.test(cause.message)) {
      error.value = null;
    } else {
      error.value = cause instanceof Error ? cause.message : "读取评论分析失败";
    }
  } finally {
    loading.value = false;
  }
}

async function runAnalysis() {
  if (!Number.isFinite(props.appid)) {
    return;
  }
  running.value = true;
  error.value = null;
  try {
    analysis.value = await analyzeReviews(props.appid);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "评论分析失败";
  } finally {
    running.value = false;
  }
}

watch(
  () => props.appid,
  () => {
    void loadLatest();
  },
  { immediate: true },
);
</script>
