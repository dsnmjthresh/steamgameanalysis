<template>
  <section>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p class="panel-title">
          RAG 知识库
        </p>
        <h2 class="mt-1 text-lg font-semibold">
          文档入库与混合检索
        </h2>
      </div>
      <div class="flex flex-wrap gap-1">
        <span class="badge text-xs">文档 {{ stats?.documents ?? 0 }}</span>
        <span class="badge text-xs">块 {{ stats?.chunks ?? 0 }}</span>
        <span :class="['badge text-xs', stats?.sqlite_vec_enabled ? 'badge-ok' : 'badge-warn']">{{ stats?.sqlite_vec_enabled ? "vec" : "cos" }}</span>
        <span :class="['badge text-xs', stats?.semantic_capability ? 'badge-ok' : 'badge-warn']">
          {{ stats?.semantic_capability ? "semantic" : "hash" }}
        </span>
      </div>
    </div>

    <div
      v-if="stats && !stats.semantic_capability"
      class="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/10 p-3 text-sm text-amber-100"
    >
      当前使用 {{ stats.embedding_provider }} 检索，属于本地 hash/关键词模式，不具备真实语义召回能力。
    </div>

    <div
      v-if="error"
      class="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
    >
      {{ error }}
    </div>

    <!-- Upload form -->
    <details class="mt-4 panel-soft rounded-lg">
      <summary class="px-3 py-2 cursor-pointer text-sm font-medium text-muted hover:text-slate-200 select-none">
        📄 上传新文档
      </summary>
      <form
        class="px-3 pb-3 grid gap-3"
        @submit.prevent="submit"
      >
        <div class="grid gap-3 lg:grid-cols-[1fr_0.5fr_0.5fr]">
          <input
            v-model="form.title"
            class="field"
            placeholder="文档标题"
            aria-label="标题"
          >
          <select
            v-model="form.source_type"
            class="field"
            aria-label="文档类型"
          >
            <option value="note">
              笔记
            </option>
            <option value="report">
              历史报告
            </option>
            <option value="news">
              Steam 新闻
            </option>
            <option value="review">
              评论摘录
            </option>
            <option value="python">
              Python 代码
            </option>
          </select>
          <input
            v-model.number="form.appid"
            class="field"
            type="number"
            min="1"
            placeholder="关联 appid (可选)"
          >
        </div>
        <textarea
          v-model="form.content"
          class="field min-h-32 resize-y"
          placeholder="粘贴需要入库的资料内容"
        />
        <div class="grid gap-3 md:grid-cols-[0.5fr_0.5fr_auto]">
          <input
            v-model.number="form.chunk_size_tokens"
            class="field"
            type="number"
            min="180"
            max="1600"
            placeholder="Chunk tokens"
          >
          <input
            v-model.number="form.chunk_overlap_tokens"
            class="field"
            type="number"
            min="0"
            max="400"
            placeholder="Overlap tokens"
          >
          <button
            class="button button-primary"
            :disabled="saving"
          >
            <Database class="h-4 w-4" />
            <span>{{ saving ? "入库中" : "入库" }}</span>
          </button>
        </div>
      </form>
    </details>

    <!-- Search -->
    <div class="mt-4 grid gap-3 md:grid-cols-[1fr_0.4fr_auto]">
      <input
        v-model="searchQuery"
        class="field"
        placeholder="检索知识库..."
        aria-label="搜索知识库"
        @keydown.enter.prevent="runSearch"
      >
      <input
        v-model.number="searchAppid"
        class="field"
        type="number"
        min="1"
        placeholder="appid 过滤"
      >
      <button
        class="button button-ghost"
        :disabled="searching"
        @click="runSearch"
      >
        <Search class="h-4 w-4" />
        <span>检索</span>
      </button>
    </div>

    <!-- Search results -->
    <TransitionGroup
      v-if="results.length"
      name="list"
      tag="div"
      class="mt-4 grid gap-2"
    >
      <article
        v-for="hit in results"
        :key="hit.chunk_id"
        class="panel-soft p-3"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1">
              <span class="font-medium text-sm">{{ hit.title }}</span>
              <span
                v-if="hit.heading"
                class="badge badge-info text-xs"
              >{{ hit.heading }}</span>
              <span
                v-if="hit.appid"
                class="badge text-xs"
              >appid {{ hit.appid }}</span>
            </div>
            <p class="mt-1 line-clamp-3 text-sm text-muted">
              {{ hit.content }}
            </p>
          </div>
          <span class="badge text-xs flex-shrink-0">score {{ hit.score.toFixed(3) }}</span>
        </div>
      </article>
    </TransitionGroup>

    <!-- Document list -->
    <div class="mt-4 grid gap-2 max-h-[300px] overflow-y-auto">
      <article
        v-for="doc in documents"
        :key="doc.id"
        class="panel-soft flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
      >
        <div class="min-w-0">
          <span class="font-medium">{{ doc.title }}</span>
          <span class="ml-2 text-xs text-muted">{{ doc.source_type }} · {{ doc.chunk_count }} chunks</span>
        </div>
        <button
          class="button icon-button button-ghost button-danger icon-button-sm"
          aria-label="删除文档"
          @click="remove(doc.id)"
        >
          <Trash2 class="h-4 w-4" />
        </button>
      </article>
      <div
        v-if="documents.length === 0"
        class="panel-soft p-4 text-sm text-muted text-center"
      >
        暂无知识文档。
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { Database, Search, Trash2 } from "lucide-vue-next";
import { createKnowledgeDocument, deleteKnowledgeDocument, getKnowledgeStats, listKnowledgeDocuments, searchKnowledge } from "@/api/client";
import type { KnowledgeChunkHit, KnowledgeDocumentRead, KnowledgeIndexStats } from "@/api/types";

const documents = ref<KnowledgeDocumentRead[]>([]);
const results = ref<KnowledgeChunkHit[]>([]);
const stats = ref<KnowledgeIndexStats | null>(null);
const saving = ref(false);
const searching = ref(false);
const error = ref<string | null>(null);
const searchQuery = ref("");
const searchAppid = ref<number | null>(null);

const form = reactive({
  title: "", source_type: "note", source_uri: "", appid: null as number | null,
  content: "", chunk_size_tokens: 700, chunk_overlap_tokens: 90,
});

async function load() {
  try {
    const [docs, indexStats] = await Promise.all([listKnowledgeDocuments(), getKnowledgeStats()]);
    documents.value = docs; stats.value = indexStats;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "读取知识库失败"; }
}

async function submit() {
  if (!form.title.trim() || !form.content.trim()) { error.value = "请填写标题和内容。"; return; }
  saving.value = true; error.value = null;
  try {
    await createKnowledgeDocument({ title: form.title.trim(), content: form.content.trim(),
      source_type: form.source_type, source_uri: form.source_uri.trim() || null,
      appid: form.appid || null, chunk_size_tokens: form.chunk_size_tokens, chunk_overlap_tokens: form.chunk_overlap_tokens });
    form.content = ""; await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "入库失败"; }
  finally { saving.value = false; }
}

async function runSearch() {
  if (!searchQuery.value.trim()) return;
  searching.value = true; error.value = null;
  try { const response = await searchKnowledge(searchQuery.value.trim(), { appid: searchAppid.value || null, limit: 6 }); results.value = response.hits; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "检索失败"; }
  finally { searching.value = false; }
}

async function remove(id: number) { await deleteKnowledgeDocument(id); await load(); }
onMounted(() => { void load(); });
</script>
