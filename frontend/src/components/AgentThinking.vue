<template>
  <div class="grid gap-2">
    <!-- Header with overall status -->
    <div class="flex items-center justify-between gap-3">
      <p class="panel-title">
        Agent 执行管线
      </p>
      <div class="flex items-center gap-2">
        <!-- Phase indicator tags -->
        <span
          v-for="phase in activePhases"
          :key="phase"
          :class="['badge text-xs', phaseTagClass(phase)]"
        >
          {{ phaseLabel(phase) }}
        </span>
        <span :class="['badge text-xs', overallStatusClass]">
          {{ overallStatusLabel }}
        </span>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!steps.length"
      class="panel-soft px-3 py-2 text-sm text-muted"
    >
      等待下一次请求
    </div>

    <!-- State pipeline visualization -->
    <div
      v-else
      class="grid gap-1.5"
    >
      <!-- Pipeline steps -->
      <article
        v-for="(step, index) in steps"
        :key="`${step.created_at}-${index}`"
        :class="[
          'panel-soft flex items-start gap-3 px-3 py-2 text-sm transition-colors duration-200',
          stepBorderClass(step.status),
          stepBgClass(step.status),
        ]"
      >
        <!-- State icon -->
        <div
          :class="[
            'mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded border transition-colors duration-300',
            iconContainerClass(step),
          ]"
          :title="statusLabel(step.status)"
        >
          <Brain
            v-if="step.kind === 'thinking'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <GitBranch
            v-else-if="step.kind === 'plan'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <Route
            v-else-if="step.kind === 'route'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <Wrench
            v-else-if="step.kind === 'tool_call'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <Eye
            v-else-if="step.kind === 'observation'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <FileText
            v-else-if="step.kind === 'synthesize'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <ShieldCheck
            v-else-if="step.kind === 'validate'"
            class="h-3.5 w-3.5"
            :class="iconColorClass(step)"
          />
          <CheckCircle2
            v-else-if="step.status === 'success'"
            class="h-3.5 w-3.5 text-emerald-300"
          />
          <AlertCircle
            v-else-if="step.status === 'failed'"
            class="h-3.5 w-3.5 text-red-400"
          />
          <RefreshCw
            v-else-if="step.status === 'retry'"
            class="h-3.5 w-3.5 text-amber-300 animate-spin"
          />
          <SkipForward
            v-else-if="step.status === 'skipped'"
            class="h-3.5 w-3.5 text-slate-500"
          />
          <Ban
            v-else-if="step.status === 'blocked'"
            class="h-3.5 w-3.5 text-red-500"
          />
          <Clock
            v-else
            class="h-3.5 w-3.5 text-slate-400"
          />
        </div>

        <!-- Content -->
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <!-- Kind label -->
            <span class="font-medium text-slate-100">{{ kindLabel(step.kind) }}</span>

            <!-- Tool name badge (clickable for evidence) -->
            <button
              v-if="step.tool_name"
              class="badge badge-clickable cursor-pointer hover:border-cyan-400/40 transition-colors"
              :title="evidenceOpen[stepKey(step, index)] ? '收起证据' : '展开证据'"
              @click="toggleEvidence(step)"
            >
              {{ step.tool_name }}
            </button>

            <!-- Status badge -->
            <span :class="['badge text-xs', statusBadgeClass(step.status)]">
              {{ statusLabel(step.status) }}
            </span>
          </div>

          <!-- Summary -->
          <p class="mt-1 text-muted leading-relaxed">
            {{ step.summary }}
          </p>

          <!-- Evidence / detail collapsible -->
          <div
            v-if="evidenceOpen[stepKey(step, index)] && hasDetail(step)"
            class="mt-2 panel-soft p-2 text-xs max-h-[250px] overflow-y-auto"
          >
            <!-- Source URL links -->
            <div
              v-if="step.detail.source_url || step.tool_name"
              class="mb-1"
            >
              <span class="text-muted">来源：</span>
              <a
                v-if="step.detail.source_url"
                :href="step.detail.source_url as string"
                target="_blank"
                rel="noreferrer"
                class="text-cyan-300 hover:underline break-all"
              >
                {{ (step.detail.source_url as string)?.slice(0, 80) }}{{ (step.detail.source_url as string)?.length > 80 ? '...' : '' }}
              </a>
              <span
                v-else
                class="text-muted"
              >内部数据</span>
            </div>

            <!-- Input params -->
            <details
              v-if="step.detail.input && Object.keys(step.detail.input as object).length"
              class="mt-1"
            >
              <summary class="cursor-pointer text-muted hover:text-slate-200">
                输入参数
              </summary>
              <pre class="mt-1 px-2 py-1 rounded bg-slate-950/50 text-slate-300 overflow-x-auto">{{ formatJSON(step.detail.input) }}</pre>
            </details>

            <!-- Additional detail fields -->
            <div
              v-if="step.detail.message"
              class="mt-1 text-amber-200/80"
            >
              ⚠ {{ step.detail.message }}
            </div>

            <!-- Confidence bar when available -->
            <div
              v-if="typeof step.detail.confidence === 'number'"
              class="mt-1.5 flex items-center gap-2"
            >
              <span class="text-muted">置信度</span>
              <div class="h-1.5 flex-1 rounded-full bg-slate-800">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :class="confidenceColor(step.detail.confidence as number)"
                  :style="{ width: `${Math.round((step.detail.confidence as number) * 100)}%` }"
                />
              </div>
              <span class="text-xs text-muted">{{ Math.round((step.detail.confidence as number) * 100) }}%</span>
            </div>
          </div>
        </div>
      </article>
    </div>

    <!-- Running indicator -->
    <div
      v-if="active"
      class="flex items-center gap-2 px-3 py-2 text-xs text-muted"
    >
      <span class="inline-block h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
      执行中...
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from "vue";
import {
  AlertCircle,
  Ban,
  Brain,
  CheckCircle2,
  Clock,
  Eye,
  FileText,
  GitBranch,
  RefreshCw,
  Route,
  ShieldCheck,
  SkipForward,
  Wrench,
} from "lucide-vue-next";

import type { AgentStepKind, AgentStepStatus, AgentToolStep } from "@/api/types";

const props = defineProps<{
  steps: AgentToolStep[];
  active?: boolean;
}>();

// Track which evidence panels are open
const evidenceOpen = reactive<Record<string, boolean>>({});

function stepKey(step: AgentToolStep, index: number): string {
  return `${step.created_at}-${index}`;
}

function toggleEvidence(step: AgentToolStep) {
  // Find the step's key
  const idx = props.steps.indexOf(step);
  if (idx < 0) return;
  const key = stepKey(step, idx);
  evidenceOpen[key] = !evidenceOpen[key];
}

function hasDetail(step: AgentToolStep): boolean {
  const d = step.detail;
  return !!(d.source_url || d.input || d.message || typeof d.confidence === "number");
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

function kindLabel(kind: AgentStepKind): string {
  const labels: Record<AgentStepKind, string> = {
    thinking: "思考",
    plan: "计划",
    route: "路由",
    tool_call: "工具调用",
    observation: "观察",
    synthesize: "合成",
    validate: "验证",
    result: "结果",
  };
  return labels[kind] || kind;
}

function statusLabel(status: AgentStepStatus): string {
  const labels: Record<AgentStepStatus, string> = {
    pending: "等待",
    running: "执行中",
    success: "成功",
    failed: "失败",
    retry: "重试",
    skipped: "跳过",
    blocked: "阻断",
    warning: "警告",
  };
  return labels[status] || status;
}

function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    plan: "📋 计划",
    act: "🔧 执行",
    observe: "👁 观察",
    synthesize: "📝 合成",
    validate: "✅ 验证",
    done: "🏁 完成",
    error: "❌ 错误",
  };
  return labels[phase] || phase;
}

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const activePhases = computed(() => {
  const seen = new Set<string>();
  const phases: string[] = [];
  for (const step of props.steps) {
    const phase = stepToPhase(step.kind);
    if (phase && !seen.has(phase)) {
      seen.add(phase);
      phases.push(phase);
    }
  }
  return phases.length ? phases : ["plan", "act", "observe", "synthesize", "validate"].slice(0, props.active ? 5 : 0);
});

function stepToPhase(kind: AgentStepKind): string {
  if (kind === "thinking" || kind === "plan" || kind === "route") return "plan";
  if (kind === "tool_call") return "act";
  if (kind === "observation") return "observe";
  if (kind === "synthesize") return "synthesize";
  if (kind === "validate") return "validate";
  if (kind === "result") return "done";
  return "";
}

const overallStatusLabel = computed(() => {
  if (props.active) return "运行中";
  const hasFailed = props.steps.some(s => s.status === "failed");
  const hasBlocked = props.steps.some(s => s.status === "blocked");
  const hasWarning = props.steps.some(s => s.status === "warning");
  if (hasFailed || hasBlocked) return "出错";
  if (hasWarning) return "完成（有警告）";
  return props.steps.length ? "完成" : "就绪";
});

const overallStatusClass = computed(() => {
  if (props.active) return "badge-warn";
  const hasFailed = props.steps.some(s => s.status === "failed" || s.status === "blocked");
  const hasWarning = props.steps.some(s => s.status === "warning");
  if (hasFailed) return "badge-err";
  if (hasWarning) return "badge-warn";
  return "badge-ok";
});

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------

function stepBorderClass(status: AgentStepStatus): string {
  switch (status) {
    case "running": return "border-l-2 border-l-cyan-400/60";
    case "success": return "";
    case "failed": return "border-l-2 border-l-red-400/50";
    case "retry": return "border-l-2 border-l-amber-400/50";
    case "skipped": return "border-l-2 border-l-slate-600/50 opacity-60";
    case "blocked": return "border-l-2 border-l-red-500/70";
    case "warning": return "border-l-2 border-l-amber-400/40";
    default: return "border-l-2 border-l-slate-600/30";
  }
}

function stepBgClass(status: AgentStepStatus): string {
  switch (status) {
    case "running": return "bg-cyan-950/10";
    case "failed": return "bg-red-950/10";
    default: return "";
  }
}

function iconContainerClass(step: AgentToolStep): string {
  switch (step.status) {
    case "running": return "border-cyan-400/40 bg-cyan-950/30";
    case "success": return "border-slate-700/70 bg-slate-950/60";
    case "failed": return "border-red-400/40 bg-red-950/30";
    case "retry": return "border-amber-400/40 bg-amber-950/30";
    case "skipped": return "border-slate-700/40 bg-slate-900/40";
    case "blocked": return "border-red-500/50 bg-red-950/40";
    case "warning": return "border-amber-400/30 bg-amber-950/20";
    default: return "border-slate-700/50 bg-slate-950/40";
  }
}

function iconColorClass(step: AgentToolStep): string {
  switch (step.status) {
    case "running": return "text-cyan-300";
    case "success": return "text-emerald-300";
    case "failed": return "text-red-400";
    case "retry": return "text-amber-300";
    case "skipped": return "text-slate-500";
    case "blocked": return "text-red-500";
    case "warning": return "text-amber-300";
    default: return "text-slate-400";
  }
}

function phaseTagClass(phase: string): string {
  if (phase === "done") return "badge-ok";
  if (phase === "error") return "badge-err";
  return "badge-info";
}

function statusBadgeClass(status: AgentStepStatus): string {
  switch (status) {
    case "running": return "badge-info";
    case "success": return "badge-ok";
    case "failed": return "badge-err";
    case "retry": return "badge-warn";
    case "skipped": return "opacity-60";
    case "blocked": return "badge-err";
    case "warning": return "badge-warn";
    default: return "";
  }
}

function confidenceColor(conf: number): string {
  if (conf >= 0.8) return "bg-emerald-400";
  if (conf >= 0.6) return "bg-amber-400";
  return "bg-red-400";
}

function formatJSON(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
</script>
