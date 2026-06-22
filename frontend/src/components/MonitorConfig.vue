<template>
  <section>
    <div class="flex items-center justify-between gap-3 mb-4">
      <div>
        <p class="panel-title">
          定时监控
        </p>
        <h2 class="mt-1 text-lg font-semibold">
          创建与管理监控任务
        </h2>
      </div>
      <button
        class="button button-ghost text-sm"
        :disabled="loading"
        @click="loadTasks"
      >
        <RefreshCcw class="h-4 w-4" />
        <span>刷新</span>
      </button>
    </div>

    <div class="grid gap-3 lg:grid-cols-[1fr_1fr_auto]">
      <label class="grid gap-1 text-sm text-muted">
        AppID
        <input
          v-model.number="form.appid"
          type="number"
          min="1"
          class="field"
          placeholder="例如 730"
          aria-label="监控目标 AppID"
        >
      </label>
      <label class="grid gap-1 text-sm text-muted">
        间隔（分钟，≥5）
        <input
          v-model.number="form.interval_minutes"
          type="number"
          min="5"
          max="1440"
          class="field"
          aria-label="采集间隔"
        >
      </label>
      <button
        class="button button-primary self-end"
        :disabled="submitting || !form.appid"
        @click="submit"
      >
        <BellPlus class="h-4 w-4" />
        <span>{{ submitting ? "创建中" : "新增" }}</span>
      </button>
    </div>

    <label class="mt-3 inline-flex items-center gap-2 text-sm text-muted cursor-pointer">
      <input
        v-model="form.enabled"
        type="checkbox"
        class="accent-cyan-400"
      >
      立即启用
    </label>

    <div
      v-if="error"
      class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
    >
      {{ error }}
    </div>

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
      class="mt-4 grid gap-2"
    >
      <article
        v-for="task in tasks"
        :key="task.id"
        class="panel-soft flex flex-wrap items-center justify-between gap-3 p-3"
      >
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-medium text-slate-100">appid {{ task.appid }}</span>
            <span :class="['badge text-xs', task.enabled ? 'badge-ok' : 'badge-warn']">{{ task.enabled ? "启用" : "停用" }}</span>
          </div>
          <p class="mt-1 text-xs text-muted">
            每 {{ task.interval_minutes }} 分钟 · {{ task.last_run_at ? `最近 ${formatDateTime(task.last_run_at)}` : "尚未运行" }}
          </p>
        </div>
        <button
          class="button icon-button button-ghost button-danger icon-button-sm"
          aria-label="删除监控任务"
          @click="confirmDelete(task.id)"
        >
          <Trash2 class="h-4 w-4" />
        </button>
      </article>
      <div
        v-if="tasks.length === 0"
        class="rounded-lg border border-dashed border-slate-700/60 p-6 text-sm text-muted text-center"
      >
        暂无监控任务。创建后可定时自动采集快照并检测异常。
      </div>
    </div>

    <!-- Confirm Dialog -->
    <Teleport to="body">
      <div
        v-if="deleteTarget !== null"
        class="confirm-overlay"
        @click.self="deleteTarget = null"
      >
        <div class="confirm-dialog">
          <p class="font-semibold text-slate-100">
            确认删除
          </p>
          <p class="mt-2 text-sm text-muted">
            确定要删除此监控任务吗？此操作不可撤销。
          </p>
          <div class="mt-4 flex justify-end gap-2">
            <button
              class="button button-ghost text-sm"
              @click="deleteTarget = null"
            >
              取消
            </button>
            <button
              class="button button-danger text-sm"
              @click="doDelete"
            >
              确认删除
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { BellPlus, RefreshCcw, Trash2 } from "lucide-vue-next";
import { createMonitor, deleteMonitor, listMonitors } from "@/api/client";
import type { MonitorTask } from "@/api/types";
import { formatDateTime } from "@/utils/format";

const props = defineProps<{ defaultInterval?: number }>();

const tasks = ref<MonitorTask[]>([]);
const loading = ref(false);
const submitting = ref(false);
const error = ref<string | null>(null);
const deleteTarget = ref<number | null>(null);

const form = reactive({ appid: 0, interval_minutes: props.defaultInterval ?? 60, enabled: true });

async function loadTasks() {
  loading.value = true; error.value = null;
  try { tasks.value = await listMonitors(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "读取失败"; }
  finally { loading.value = false; }
}

async function submit() {
  if (!form.appid || form.appid < 1) { error.value = "请输入有效的 AppID。"; return; }
  if (form.interval_minutes < 5) { error.value = "最小间隔为 5 分钟。"; return; }
  submitting.value = true; error.value = null;
  try { await createMonitor({ appid: form.appid, interval_minutes: form.interval_minutes, enabled: form.enabled }); form.appid = 0; await loadTasks(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "创建失败"; }
  finally { submitting.value = false; }
}

function confirmDelete(id: number) { deleteTarget.value = id; }
async function doDelete() {
  if (deleteTarget.value === null) return;
  const id = deleteTarget.value; deleteTarget.value = null;
  try { await deleteMonitor(id); await loadTasks(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "删除失败"; }
}

watch(() => props.defaultInterval, (v) => { if (typeof v === "number" && form.interval_minutes === 60) form.interval_minutes = v; }, { immediate: true });
void loadTasks();
</script>
