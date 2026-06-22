<template>
  <section>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p class="panel-title">
          游戏别名库
        </p>
        <h2 class="mt-1 text-lg font-semibold">
          中文名、缩写与社区叫法
        </h2>
      </div>
      <div class="flex items-center gap-2">
        <span class="badge">{{ aliases.length }} 条</span>
        <button
          class="button button-ghost text-sm"
          :disabled="loading"
          @click="load"
        >
          <RefreshCcw class="h-4 w-4" />
          <span>刷新</span>
        </button>
      </div>
    </div>

    <div
      v-if="error"
      class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
    >
      {{ error }}
    </div>

    <!-- Add form -->
    <form
      class="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto]"
      @submit.prevent="submit"
    >
      <input
        v-model.number="form.appid"
        class="field"
        type="number"
        min="1"
        placeholder="AppID"
        aria-label="AppID"
      >
      <input
        v-model="form.canonical_name"
        class="field"
        placeholder="标准名称"
        aria-label="标准名称"
      >
      <input
        v-model="form.alias"
        class="field"
        placeholder="中文别名或缩写"
        aria-label="别名"
      >
      <button
        class="button button-primary"
        :disabled="saving"
      >
        <Plus class="h-4 w-4" />
        <span>添加</span>
      </button>
    </form>

    <div class="mt-3 grid gap-3 md:grid-cols-3">
      <select
        v-model="form.alias_type"
        class="field"
        aria-label="别名类型"
      >
        <option value="nickname">
          社区叫法
        </option>
        <option value="zh_name">
          中文名
        </option>
        <option value="abbreviation">
          缩写
        </option>
        <option value="official">
          官方别名
        </option>
      </select>
      <input
        v-model="form.locale"
        class="field"
        placeholder="locale (zh-CN)"
        aria-label="语言"
      >
      <input
        v-model.number="form.confidence"
        class="field"
        type="number"
        min="0"
        max="1"
        step="0.01"
        placeholder="置信度 (0-1)"
      >
    </div>

    <!-- Filter -->
    <div class="mt-4 flex flex-col gap-3 md:flex-row">
      <input
        v-model="query"
        class="field flex-1"
        placeholder="筛选别名或游戏名"
        aria-label="搜索别名"
        @keydown.enter.prevent="load"
      >
      <button
        class="button button-ghost md:w-24"
        :disabled="loading"
        @click="load"
      >
        <Search class="h-4 w-4" />
        <span>筛选</span>
      </button>
    </div>

    <!-- List -->
    <div
      v-if="loading"
      class="mt-4 space-y-2"
    >
      <div
        v-for="i in 3"
        :key="i"
        class="skeleton skeleton-text"
      />
    </div>
    <div
      v-else
      class="mt-4 grid gap-2 max-h-[400px] overflow-y-auto"
    >
      <article
        v-for="item in aliases"
        :key="item.id"
        class="panel-soft p-3 text-sm"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-slate-100">{{ item.alias }}</span>
              <span class="badge badge-info text-xs">{{ item.alias_type }}</span>
              <span class="badge text-xs">appid {{ item.appid }}</span>
            </div>
            <p class="mt-1 text-xs text-muted">
              {{ item.canonical_name }} · {{ item.locale }} · {{ Math.round(item.confidence * 100) }}%
            </p>
          </div>
          <button
            class="button icon-button button-ghost button-danger icon-button-sm"
            aria-label="删除别名"
            @click="remove(item.id)"
          >
            <Trash2 class="h-4 w-4" />
          </button>
        </div>
      </article>
      <div
        v-if="aliases.length === 0"
        class="rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
      >
        暂无匹配别名。添加别名后可通过中文搜索匹配游戏。
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { Plus, RefreshCcw, Search, Trash2 } from "lucide-vue-next";
import { createGameAlias, deleteGameAlias, listGameAliases } from "@/api/client";
import type { GameAliasRead } from "@/api/types";

const aliases = ref<GameAliasRead[]>([]);
const query = ref("");
const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);

const form = reactive({
  appid: null as number | null, canonical_name: "", alias: "",
  locale: "zh-CN", alias_type: "nickname", source: "user", confidence: 0.9,
});

async function load() {
  loading.value = true; error.value = null;
  try { aliases.value = await listGameAliases(query.value.trim() || undefined, 120); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "读取别名失败"; }
  finally { loading.value = false; }
}

async function submit() {
  if (!form.appid || !form.canonical_name.trim() || !form.alias.trim()) { error.value = "请填写 AppID、标准名称和别名。"; return; }
  saving.value = true; error.value = null;
  try {
    await createGameAlias({ appid: form.appid, canonical_name: form.canonical_name.trim(), alias: form.alias.trim(),
      locale: form.locale, alias_type: form.alias_type, source: form.source, confidence: form.confidence });
    form.alias = ""; await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "保存失败"; }
  finally { saving.value = false; }
}

async function remove(id: number) { await deleteGameAlias(id); await load(); }
onMounted(() => { void load(); });
</script>
