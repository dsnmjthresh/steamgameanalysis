<script setup lang="ts">
import { onMounted, ref } from "vue";
import { BookOpen, Search, Trash2, Upload } from "lucide-vue-next";
import {
  createKnowledgeDocument,
  deleteKnowledgeDocument,
  getKnowledgeStats,
  listKnowledgeDocuments,
  searchKnowledge,
} from "@/api/client";
import type { KnowledgeDocumentRead, KnowledgeChunkHit, KnowledgeIndexStats } from "@/api/types";

// ---- Stats ----
const stats = ref<KnowledgeIndexStats | null>(null);

async function loadStats() {
  try {
    stats.value = await getKnowledgeStats();
  } catch {
    // stats unavailable
  }
}

// ---- Upload ----
const uploadForm = ref({
  title: "",
  source_type: "report",
  appid: null as number | null,
  content: "",
});
const uploading = ref(false);
const uploadError = ref<string | null>(null);
const uploadSuccess = ref<string | null>(null);

async function handleUpload() {
  if (!uploadForm.value.title.trim() || !uploadForm.value.content.trim()) return;
  uploading.value = true;
  uploadError.value = null;
  uploadSuccess.value = null;
  try {
    await createKnowledgeDocument({
      title: uploadForm.value.title,
      content: uploadForm.value.content,
      source_type: uploadForm.value.source_type,
      appid: uploadForm.value.appid ?? undefined,
    });
    uploadForm.value = { title: "", source_type: "report", appid: null, content: "" };
    uploadSuccess.value = "文档已上传";
    await Promise.all([loadDocuments(), loadStats()]);
  } catch (err) {
    uploadError.value = err instanceof Error ? err.message : "上传失败";
  } finally {
    uploading.value = false;
  }
}

// ---- Document List ----
const documents = ref<KnowledgeDocumentRead[]>([]);
const loadingDocs = ref(false);

async function loadDocuments() {
  loadingDocs.value = true;
  try {
    documents.value = await listKnowledgeDocuments(50);
  } catch {
    documents.value = [];
  } finally {
    loadingDocs.value = false;
  }
}

async function deleteDoc(id: number) {
  try {
    await deleteKnowledgeDocument(id);
    documents.value = documents.value.filter((d) => d.id !== id);
    await loadStats();
  } catch {
    // delete failed silently
  }
}

// ---- Search ----
const searchQuery = ref("");
const searchAppid = ref<number | null>(null);
const searchResults = ref<KnowledgeChunkHit[]>([]);
const searching = ref(false);
const searchDebug = ref<Record<string, unknown>>({});

async function handleSearch() {
  if (!searchQuery.value.trim()) return;
  searching.value = true;
  try {
    const result = await searchKnowledge(searchQuery.value, {
      appid: searchAppid.value ?? null,
      limit: 10,
    });
    searchResults.value = result.hits;
    searchDebug.value = result.debug ?? {};
  } catch {
    searchResults.value = [];
  } finally {
    searching.value = false;
  }
}

onMounted(() => {
  loadStats();
  loadDocuments();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <section class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="panel-title">
            知识库
          </p>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">
            RAG 知识库管理
          </h1>
          <p class="mt-1 text-sm text-muted">
            文档上传、检索测试、分块预览
          </p>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span class="badge text-xs">文档 {{ stats?.documents ?? 0 }}</span>
          <span class="badge text-xs">分块 {{ stats?.chunks ?? 0 }}</span>
          <span :class="['badge text-xs', stats?.sqlite_vec_enabled ? 'badge-ok' : 'badge-warn']">
            {{ stats?.sqlite_vec_enabled ? "vec" : "cos" }}
          </span>
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
    </section>

    <div class="grid gap-5 xl:grid-cols-2">
      <!-- Upload & Document List -->
      <div class="space-y-5">
        <!-- Upload -->
        <section class="panel p-4">
          <div class="flex items-center gap-2 mb-3">
            <Upload class="h-4 w-4 text-cyan-400" />
            <h2 class="font-semibold">
              上传文档
            </h2>
          </div>
          <form
            class="grid gap-3"
            @submit.prevent="handleUpload"
          >
            <div class="grid gap-3 sm:grid-cols-3">
              <input
                v-model="uploadForm.title"
                class="field sm:col-span-2"
                placeholder="文档标题"
              >
              <input
                v-model.number="uploadForm.appid"
                class="field"
                type="number"
                min="1"
                placeholder="appid（可选）"
              >
            </div>
            <div class="grid gap-3 sm:grid-cols-[1fr_auto]">
              <select
                v-model="uploadForm.source_type"
                class="field"
              >
                <option value="report">
                  报告
                </option>
                <option value="article">
                  文章
                </option>
                <option value="python">
                  Python 代码
                </option>
                <option value="patch_note">
                  更新日志
                </option>
                <option value="other">
                  其他
                </option>
              </select>
              <button
                class="button button-primary"
                :disabled="uploading || !uploadForm.title.trim() || !uploadForm.content.trim()"
              >
                {{ uploading ? "上传中..." : "上传" }}
              </button>
            </div>
            <textarea
              v-model="uploadForm.content"
              class="field min-h-[120px]"
              placeholder="文档内容（Markdown 格式）..."
            />
            <div
              v-if="uploadError"
              class="text-xs text-rose-400"
            >
              {{ uploadError }}
            </div>
            <div
              v-if="uploadSuccess"
              class="text-xs text-emerald-400"
            >
              {{ uploadSuccess }}
            </div>
          </form>
        </section>

        <!-- Document List -->
        <section class="panel p-4">
          <div class="flex items-center gap-2 mb-3">
            <BookOpen class="h-4 w-4 text-cyan-400" />
            <h2 class="font-semibold">
              文档列表
            </h2>
            <span class="text-xs text-muted">({{ documents.length }})</span>
          </div>
          <div
            v-if="loadingDocs"
            class="space-y-2"
          >
            <div
              v-for="i in 3"
              :key="i"
              class="skeleton skeleton-text"
            />
          </div>
          <div
            v-else
            class="grid gap-2 max-h-[500px] overflow-y-auto"
          >
            <article
              v-for="doc in documents"
              :key="doc.id"
              class="panel-soft p-3 text-sm flex items-start justify-between gap-2"
            >
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="font-medium truncate">{{ doc.title }}</span>
                  <span class="badge text-xs">{{ doc.source_type }}</span>
                  <span
                    v-if="doc.appid"
                    class="badge text-xs"
                  >appid {{ doc.appid }}</span>
                </div>
                <p class="mt-1 text-xs text-muted">
                  分块数: {{ doc.chunk_count }} · 创建于 {{ new Date(doc.created_at).toLocaleDateString("zh-CN") }}
                </p>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <button
                  class="button button-ghost icon-button-sm"
                  title="删除"
                  @click="deleteDoc(doc.id)"
                >
                  <Trash2 class="h-3.5 w-3.5 text-rose-400" />
                </button>
              </div>
            </article>
            <div
              v-if="documents.length === 0 && !loadingDocs"
              class="text-sm text-muted py-4 text-center"
            >
              暂无文档，请上传
            </div>
          </div>
        </section>
      </div>

      <!-- Search -->
      <section class="panel p-4">
        <div class="flex items-center gap-2 mb-3">
          <Search class="h-4 w-4 text-cyan-400" />
          <h2 class="font-semibold">
            检索测试
          </h2>
        </div>
        <div class="grid gap-3">
          <div class="grid gap-3 sm:grid-cols-[1fr_auto]">
            <input
              v-model="searchQuery"
              class="field"
              placeholder="输入搜索查询..."
              @keyup.enter="handleSearch"
            >
            <button
              class="button button-primary"
              :disabled="searching || !searchQuery.trim()"
              @click="handleSearch"
            >
              {{ searching ? "搜索中..." : "搜索" }}
            </button>
          </div>
          <input
            v-model.number="searchAppid"
            class="field w-full sm:w-40"
            type="number"
            min="1"
            placeholder="appid 过滤（可选）"
          >

          <!-- Results -->
          <div
            v-if="searchResults.length > 0"
            class="mt-2 grid gap-2"
          >
            <div class="flex items-center justify-between text-xs text-muted">
              <span>{{ searchResults.length }} 结果</span>
              <span>后端: {{ searchDebug.vector_backend ?? "?" }}</span>
            </div>
            <article
              v-for="hit in searchResults"
              :key="hit.chunk_id"
              class="panel-soft p-3 text-sm"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-medium">文档 #{{ hit.document_id }}</span>
                <span class="badge text-xs">得分 {{ hit.score.toFixed(3) }}</span>
              </div>
              <div
                v-if="hit.heading"
                class="mt-1 text-xs text-cyan-400"
              >
                {{ hit.heading }}
              </div>
              <p class="mt-1 text-xs text-muted line-clamp-3">
                {{ hit.content }}
              </p>
            </article>
          </div>
          <div
            v-else-if="!searching && searchQuery"
            class="text-sm text-muted py-2"
          >
            无搜索结果
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
