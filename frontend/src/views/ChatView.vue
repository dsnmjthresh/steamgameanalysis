<template>
  <div class="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
    <!-- Chat Panel -->
    <section
      class="panel p-4 flex flex-col"
      style="min-height: calc(100vh - 140px)"
    >
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="panel-title">
            Agent
          </p>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">
            AI 分析助手
          </h1>
          <p class="mt-1 text-sm text-muted">
            {{ autoCollect ? '自动采集快照后进行分析' : '只读模式，不采集新数据' }}
          </p>
        </div>
        <label
          class="badge cursor-pointer select-none hover:border-cyan-400/30 transition-colors"
          :class="autoCollect ? 'badge-ok' : ''"
        >
          <input
            v-model="autoCollect"
            type="checkbox"
            class="mr-1.5 accent-cyan-400"
          >
          {{ autoCollect ? '自动采集' : '只读' }}
        </label>
      </div>

      <!-- Messages Area -->
      <div
        ref="messagesContainer"
        class="mt-4 flex-1 space-y-3 overflow-y-auto pr-1"
        style="max-height: calc(100vh - 300px)"
      >
        <TransitionGroup name="list">
          <article
            v-for="message in messages"
            :key="message.id"
            class="panel-soft p-4"
            :class="message.role === 'assistant' ? 'border-l-2 border-l-cyan-400/30' : ''"
          >
            <div class="flex items-center justify-between gap-2 mb-2">
              <span :class="['badge text-xs', message.role === 'assistant' ? 'badge-info' : '']">
                {{ message.role === "assistant" ? "🤖 助手" : "👤 你" }}
              </span>
              <span
                v-if="message.time"
                class="text-xs text-muted"
              >{{ formatTime(message.time) }}</span>
            </div>
            <p
              v-if="message.role === 'user'"
              class="whitespace-pre-wrap text-sm leading-7 text-slate-100"
            >
              {{ message.content }}
            </p>
            <div
              v-else
              class="text-sm"
            >
              <MarkdownRenderer :content="message.content" />
              <!-- Write Confirmation -->
              <div
                v-if="message.result?.requires_human_confirmation"
                class="mt-3 panel-soft p-3 border-l-2 border-l-amber-400/40"
              >
                <p class="text-sm text-amber-200">
                  此操作需要确认后才能执行。
                </p>
                <div class="mt-2 flex gap-2">
                  <button
                    class="button button-primary text-xs"
                    @click="confirmAction(message)"
                  >
                    ✅ 确认执行
                  </button>
                  <button
                    class="button button-ghost text-xs"
                    @click="cancelAction(message)"
                  >
                    ✖ 取消
                  </button>
                </div>
              </div>
              <!-- Clarification Candidates -->
              <div
                v-if="message.result?.candidates?.length"
                class="mt-3"
              >
                <p class="text-sm text-muted mb-2">
                  请选择一个选项来继续：
                </p>
                <div class="grid gap-1.5">
                  <button
                    v-for="candidate in message.result.candidates"
                    :key="candidate.label"
                    class="panel-soft px-3 py-2 text-left text-sm hover:border-cyan-400/30 transition-colors cursor-pointer"
                    @click="clarify(candidate.action_query || candidate.label)"
                  >
                    <span class="font-medium text-cyan-300">{{ candidate.label }}</span>
                    <span
                      v-if="candidate.description"
                      class="ml-2 text-muted"
                    >— {{ candidate.description }}</span>
                  </button>
                </div>
              </div>
              <div
                v-if="message.result"
                class="mt-4 space-y-3"
              >
                <!-- Evidence (collapsible) -->
                <details
                  v-if="message.result.evidence.length"
                  class="panel-soft rounded-lg"
                >
                  <summary class="px-3 py-2 cursor-pointer text-xs font-medium text-muted hover:text-slate-200 select-none">
                    证据 · {{ message.result.evidence.length }} 条
                  </summary>
                  <div class="px-3 pb-3 grid gap-2 max-h-[300px] overflow-y-auto">
                    <article
                      v-for="evidence in message.result.evidence"
                      :key="evidence.source + evidence.summary"
                      class="panel-soft px-3 py-2 text-xs"
                    >
                      <div class="flex items-center justify-between gap-2">
                        <span class="font-medium">{{ evidence.source }}</span>
                        <span class="text-muted">{{ formatDateTime(evidence.collected_at) }}</span>
                      </div>
                      <p class="mt-1 text-muted">
                        {{ evidence.summary }}
                      </p>
                      <a
                        v-if="evidence.url"
                        :href="evidence.url"
                        target="_blank"
                        rel="noreferrer"
                        class="mt-1 inline-flex items-center gap-1 text-cyan-300 text-xs"
                      >
                        <ExternalLink class="h-3 w-3" /> 来源
                      </a>
                    </article>
                  </div>
                </details>

                <!-- Assumptions & Uncertainties (collapsible) -->
                <details
                  v-if="message.result.assumptions.length || message.result.uncertainties.length"
                  class="panel-soft rounded-lg"
                >
                  <summary class="px-3 py-2 cursor-pointer text-xs font-medium text-muted hover:text-slate-200 select-none">
                    假设 · {{ message.result.assumptions.length }} / 不确定项 · {{ message.result.uncertainties.length }}
                  </summary>
                  <div class="px-3 pb-3 grid gap-1">
                    <div
                      v-for="item in message.result.assumptions"
                      :key="item"
                      class="panel-soft px-2 py-1.5 text-xs text-muted"
                    >
                      💡 {{ item }}
                    </div>
                    <div
                      v-for="item in message.result.uncertainties"
                      :key="item"
                      class="panel-soft px-2 py-1.5 text-xs text-amber-200/80"
                    >
                      ⚠ {{ item }}
                    </div>
                  </div>
                </details>

                <!-- Agent Steps (collapsible) -->
                <AgentThinking
                  v-if="message.result.agent_steps.length"
                  :steps="message.result.agent_steps"
                />

                <!-- Background Task Trigger -->
                <div
                  v-if="message.result?.task_type && isLongTask(message.result.task_type)"
                  class="mt-3"
                >
                  <button
                    class="button button-ghost text-xs"
                    @click="submitBackgroundTask(message.result!.task_type, messages.find(m => m.role === 'user' && m.id < message.id)?.content ?? message.content, message.result!.games[0]?.appid)"
                  >
                    后台运行（避免超时）
                  </button>
                </div>
              </div>
            </div>
          </article>
        </TransitionGroup>
      </div>

      <!-- Input -->
      <form
        class="mt-4 flex flex-col gap-2 sm:flex-row"
        @submit.prevent="send()"
      >
        <input
          v-model="query"
          class="field flex-1"
          placeholder="输入问题，如：CS2最近在线人数趋势如何？"
          aria-label="聊天输入"
          :disabled="sending"
        >
        <button
          class="button button-primary sm:w-28"
          :disabled="sending || !query.trim()"
        >
          <MessageSquareText class="h-4 w-4" />
          <span>{{ sending ? "思考中" : "发送" }}</span>
        </button>
      </form>
    </section>

    <!-- Sidebar -->
    <section class="space-y-4">
      <div class="panel p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="panel-title">
              会话
            </p>
            <h2 class="mt-1 text-lg font-semibold">
              当前对话
            </h2>
          </div>
          <span class="badge badge-info">{{ conversationId ? `#${conversationId}` : "未创建" }}</span>
        </div>
        <div class="mt-4 grid gap-2 text-sm">
          <div class="panel-soft flex items-center justify-between px-3 py-2">
            <span class="text-muted">消息数</span>
            <span class="font-medium">{{ messages.length }}</span>
          </div>
          <div class="panel-soft flex items-center justify-between px-3 py-2">
            <span class="text-muted">采集模式</span>
            <span :class="autoCollect ? 'text-green-400' : 'text-muted'">{{ autoCollect ? "自动" : "只读" }}</span>
          </div>
        </div>
        <!-- Live Steps -->
        <div
          v-if="liveSteps.length > 0 || sending"
          class="mt-4"
        >
          <p class="panel-title mb-2">
            实时进度
          </p>
          <AgentThinking
            :steps="liveSteps"
            :active="sending"
          />
        </div>

        <!-- Background Tasks -->
        <div
          v-if="runningTasks.size > 0"
          class="mt-4 space-y-3"
        >
          <p class="panel-title">
            后台任务
          </p>
          <TaskPollingCard
            v-for="[key, info] in Array.from(runningTasks.entries())"
            :key="key"
            :task-id="info.taskId"
            :label="info.label"
            @completed="onBackgroundTaskCompleted"
            @failed="() => {}"
          />
        </div>

        <button
          v-if="messages.length > 0"
          class="mt-4 button button-ghost text-xs w-full"
          @click="messages.splice(0); conversationId = null"
        >
          <Trash2 class="h-3.5 w-3.5" />
          <span>清空对话（开始新会话）</span>
        </button>
      </div>

      <!-- History Reports -->
      <div class="panel p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="panel-title">
              历史报告
            </p>
            <h2 class="mt-1 text-lg font-semibold">
              分析输出
            </h2>
          </div>
          <button
            class="button icon-button button-ghost icon-button-sm"
            aria-label="刷新报告"
            @click="reloadReports"
          >
            <RefreshCcw class="h-3.5 w-3.5" />
          </button>
        </div>
        <div
          v-if="loadingReports"
          class="mt-4 space-y-2"
        >
          <div
            v-for="i in 2"
            :key="i"
            class="skeleton skeleton-text"
          />
        </div>
        <div
          v-else
          class="mt-4 grid gap-2 max-h-[400px] overflow-y-auto"
        >
          <article
            v-for="report in workspace.recentReports"
            :key="report.id"
            class="panel-soft p-3 text-sm"
          >
            <p class="font-medium text-slate-100 line-clamp-1">
              {{ report.query }}
            </p>
            <p class="mt-1 text-xs text-muted line-clamp-2">
              {{ report.answer_markdown }}
            </p>
            <div class="mt-2 flex items-center gap-2">
              <a
                :href="reportExportUrl(report.id, 'markdown')"
                class="button button-ghost px-2 py-1 text-xs"
              >MD</a>
              <a
                :href="reportExportUrl(report.id, 'json')"
                class="button button-ghost px-2 py-1 text-xs"
              >JSON</a>
            </div>
          </article>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, reactive, ref, watch } from "vue";
import { ExternalLink, MessageSquareText, RefreshCcw, Trash2 } from "lucide-vue-next";
import { reportExportUrl, streamChat, createTask } from "@/api/client";
import AgentThinking from "@/components/AgentThinking.vue";
import MarkdownRenderer from "@/components/MarkdownRenderer.vue";
import TaskPollingCard from "@/components/TaskPollingCard.vue";
import { formatDateTime } from "@/utils/format";
import type { AgentAnalysisResult, AgentToolStep, ChatStreamEvent } from "@/api/types";
import { useWorkspaceStore } from "@/stores/workspace";

interface MessageItem { id: string; role: "user" | "assistant"; content: string; time: string; result?: AgentAnalysisResult; }
const MAX_MESSAGES = 50;

const workspace = useWorkspaceStore();
const query = ref("");
const autoCollect = ref(false);  // default read-only to match backend
const sending = ref(false);
const conversationId = ref<number | null>(null);
const messages = reactive<MessageItem[]>([]);
const liveSteps = reactive<AgentToolStep[]>([]);
const loadingReports = ref(false);
const messagesContainer = ref<HTMLElement | null>(null);

// Task polling support for long-running background tasks
const runningTasks = reactive<Map<string, { taskId: number; label: string }>>(new Map());

function isLongTask(taskType: string | undefined): boolean {
  return taskType === "web_sentiment" || taskType === "report_generate" || taskType === "review_analyze";
}

async function submitBackgroundTask(taskType: string, query: string, appid?: number) {
  try {
    const task = await createTask({
      task_type: taskType,
      input_data: { query, appid },
    });
    const key = crypto.randomUUID();
    const labelMap: Record<string, string> = {
      web_sentiment: "网页舆情分析",
      report_generate: "报告生成",
      review_analyze: "评论分析",
    };
    runningTasks.set(key, { taskId: task.id, label: labelMap[taskType] || "后台任务" });
  } catch (err) {
    console.error("Failed to create background task:", err);
  }
}

function onBackgroundTaskCompleted(_result: Record<string, unknown>) {
  workspace.loadReports();
}

function formatTime(iso: string) { return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); }

async function send(confirmedWrite = false) {
  const value = query.value.trim();
  if (!value || sending.value) return;
  const time = new Date().toISOString();
  messages.push({ id: crypto.randomUUID(), role: "user", content: value, time });
  query.value = "";
  sending.value = true;
  liveSteps.splice(0);

  try {
    const response = await streamChat(
      { query: value, conversation_id: conversationId.value, auto_collect: autoCollect.value, confirmed_write: confirmedWrite },
      handleStreamEvent,
    );
    conversationId.value = response.conversation_id;
    liveSteps.splice(0, liveSteps.length, ...response.result.agent_steps);
    messages.push({ id: crypto.randomUUID(), role: "assistant", content: response.result.answer, time: new Date().toISOString(), result: response.result });
    await workspace.loadReports();
  } catch (cause) {
    messages.push({ id: crypto.randomUUID(), role: "assistant", content: cause instanceof Error ? `❌ ${cause.message}` : "请求失败，请重试。", time: new Date().toISOString() });
  } finally {
    sending.value = false;
    while (messages.length > MAX_MESSAGES) messages.splice(0, 2);
  }
}

function confirmAction(message: MessageItem) {
  // Re-send the last user query with write confirmation
  const lastUser = [...messages].reverse().find(m => m.role === "user");
  if (lastUser) {
    message.result = undefined;  // Remove old result from display
    query.value = lastUser.content;
    send(true);  // confirmed_write = true
  }
}

function cancelAction(message: MessageItem) {
  // Replace the confirmation message with a cancellation note
  message.content = "操作已取消。";
  if (message.result) {
    message.result.requires_human_confirmation = false;
  }
}

function clarify(actionQuery: string) {
  query.value = actionQuery;
  send(false);
}

function handleStreamEvent(item: ChatStreamEvent) {
  const eventType = item.event;
  // Map SSE event types to step kinds
  const kindMap: Record<string, AgentToolStep["kind"]> = {
    thinking: "thinking",
    route: "route",
    tool_call: "tool_call",
    observation: "observation",
    tool_error: "observation",
    validation: "validate",
    plan: "plan",
    synthesize: "synthesize",
    reflection: "validate",
  };
  const kind = kindMap[eventType];
  if (!kind) return;

  // Determine status from event type
  let status: AgentToolStep["status"] = "success";
  if (eventType === "tool_error") status = "failed";
  else if (eventType === "validation") status = "warning";

  // Check if we should replace a pending step of the same kind
  const pendingIdx = liveSteps.findIndex(s => s.kind === kind && s.status === "pending");
  if (pendingIdx >= 0) {
    liveSteps[pendingIdx] = {
      kind,
      summary: typeof item.data.summary === "string" ? item.data.summary : item.event,
      tool_name: typeof item.data.tool === "string" ? item.data.tool : null,
      status,
      detail: item.data,
      created_at: new Date().toISOString(),
    };
    return;
  }

  liveSteps.push({
    kind,
    summary: typeof item.data.summary === "string" ? item.data.summary : item.event,
    tool_name: typeof item.data.tool === "string" ? item.data.tool : null,
    status,
    detail: item.data,
    created_at: new Date().toISOString(),
  });
}

async function reloadReports() {
  loadingReports.value = true;
  try { await workspace.loadReports(); }
  finally { loadingReports.value = false; }
}

// Auto-scroll on new messages
watch(() => messages.length, () => { nextTick(() => { if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight; }); });
</script>
