<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { LoaderCircle, CheckCircle2, XCircle, Ban } from "lucide-vue-next";
import { cancelTask, getTask } from "@/api/client";
import type { TaskRead } from "@/api/types";

const props = defineProps<{
  taskId: number;
  label: string;
}>();

const emit = defineEmits<{
  (e: "completed", result: Record<string, unknown>): void;
  (e: "failed", error: string): void;
}>();

const task = ref<TaskRead | null>(null);
const polling = ref(true);
const cancelling = ref(false);
const error = ref<string | null>(null);

let timer: ReturnType<typeof setInterval> | null = null;

function statusLabel(status: string) {
  const map: Record<string, string> = {
    pending: "等待中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return map[status] ?? status;
}

function statusClass(status: string) {
  const map: Record<string, string> = {
    pending: "badge",
    running: "badge badge-ok",
    completed: "badge badge-ok",
    failed: "badge bg-red-500/20 text-red-400",
    cancelled: "badge bg-amber-500/20 text-amber-400",
  };
  return map[status] ?? "badge";
}

async function poll() {
  if (!polling.value) return;
  try {
    const t = await getTask(props.taskId);
    task.value = t;
    if (t.status === "completed") {
      polling.value = false;
      if (timer) clearInterval(timer);
      emit("completed", t.result_data);
    } else if (t.status === "failed") {
      polling.value = false;
      if (timer) clearInterval(timer);
      emit("failed", t.error_message ?? "未知错误");
    } else if (t.status === "cancelled") {
      polling.value = false;
      if (timer) clearInterval(timer);
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "轮询失败";
  }
}

async function handleCancel() {
  cancelling.value = true;
  try {
    await cancelTask(props.taskId);
    polling.value = false;
    if (timer) clearInterval(timer);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "取消失败";
  } finally {
    cancelling.value = false;
  }
}

onMounted(() => {
  poll();
  timer = setInterval(poll, 3000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="panel-soft p-4 mt-3">
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <LoaderCircle
          v-if="task?.status === 'running' || task?.status === 'pending'"
          class="w-4 h-4 text-cyan-400 animate-spin"
        />
        <CheckCircle2
          v-else-if="task?.status === 'completed'"
          class="w-4 h-4 text-emerald-400"
        />
        <XCircle
          v-else-if="task?.status === 'failed'"
          class="w-4 h-4 text-red-400"
        />
        <Ban
          v-else-if="task?.status === 'cancelled'"
          class="w-4 h-4 text-amber-400"
        />
        <span class="text-sm font-medium">{{ label }}</span>
        <span :class="task ? statusClass(task.status) : 'badge'">
          {{ task ? statusLabel(task.status) : "加载中..." }}
        </span>
      </div>
      <button
        v-if="task && (task.status === 'pending' || task.status === 'running')"
        class="button button-ghost text-xs"
        :disabled="cancelling"
        @click="handleCancel"
      >
        {{ cancelling ? "取消中..." : "取消" }}
      </button>
    </div>

    <!-- Progress bar -->
    <div
      v-if="task"
      class="mt-3"
    >
      <div class="progress-bar">
        <div
          class="progress-bar-fill"
          :class="{ running: task.status === 'running' }"
          :style="{ width: `${task.progress_pct}%` }"
        />
      </div>
      <div class="flex items-center justify-between mt-1.5 text-xs text-muted">
        <span>{{ task.progress_message ?? "" }}</span>
        <span>{{ Math.round(task.progress_pct) }}%</span>
      </div>

      <!-- Error message -->
      <div
        v-if="task.status === 'failed' && task.error_message"
        class="mt-2 text-xs text-red-400"
      >
        {{ task.error_message }}
      </div>

      <!-- Result preview (expandable) -->
      <details
        v-if="task.status === 'completed' && Object.keys(task.result_data).length > 0"
        class="mt-2"
      >
        <summary class="text-xs cursor-pointer text-cyan-400 hover:text-cyan-300">
          查看结果
        </summary>
        <pre class="mt-1 text-xs overflow-auto max-h-48 p-2 rounded bg-black/20">{{ JSON.stringify(task.result_data, null, 2) }}</pre>
      </details>
    </div>

    <div
      v-if="error"
      class="mt-2 text-xs text-red-400"
    >
      {{ error }}
    </div>
  </div>
</template>
