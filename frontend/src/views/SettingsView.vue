<template>
  <div class="space-y-5">
    <section class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="panel-title">
            设置
          </p>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">
            地区、语言与模型
          </h1>
          <p class="mt-1 text-sm text-muted">
            修改设置后请点击保存
          </p>
        </div>
        <div class="flex items-center gap-2">
          <span
            v-if="hasChanges"
            class="badge badge-warn text-xs"
          >未保存的更改</span>
          <button
            class="button button-primary"
            :disabled="saving"
            @click="save"
          >
            <Save class="h-4 w-4" />
            <span>{{ saving ? "保存中" : "保存" }}</span>
          </button>
        </div>
      </div>

      <div
        v-if="error"
        class="mt-4 rounded-lg border border-rose-400/20 bg-rose-400/10 p-3 text-sm text-rose-200"
      >
        {{ error }}
      </div>
      <div
        v-if="successMsg"
        class="mt-4 rounded-lg border border-emerald-400/20 bg-emerald-400/10 p-3 text-sm text-emerald-200"
      >
        {{ successMsg }}
      </div>

      <!-- Basic Settings -->
      <div class="mt-5 grid gap-4 lg:grid-cols-2">
        <div class="panel-soft p-4">
          <p class="panel-title">
            默认查询
          </p>
          <div class="mt-3 grid gap-3">
            <label class="grid gap-1 text-sm text-muted">
              地区代码 (CC)
              <input
                v-model="form.default_cc"
                class="field"
                maxlength="2"
                placeholder="CN"
                @input="markDirty"
              >
            </label>
            <label class="grid gap-1 text-sm text-muted">
              语言
              <input
                v-model="form.default_language"
                class="field"
                placeholder="schinese"
                @input="markDirty"
              >
            </label>
            <label class="grid gap-1 text-sm text-muted">
              币种
              <input
                v-model="form.default_currency"
                class="field"
                maxlength="3"
                placeholder="CNY"
                @input="markDirty"
              >
            </label>
          </div>
        </div>

        <div class="panel-soft p-4">
          <p class="panel-title">
            模型与采集
          </p>
          <div class="mt-3 grid gap-3">
            <label class="grid gap-1 text-sm text-muted">
              DeepSeek 模型
              <input
                v-model="form.deepseek_model"
                class="field"
                placeholder="deepseek-v4-pro"
                @input="markDirty"
              >
            </label>
            <label class="grid gap-1 text-sm text-muted">
              采集间隔（分钟）
              <input
                v-model.number="form.collection_interval_minutes"
                type="number"
                min="5"
                max="1440"
                class="field"
                @input="markDirty"
              >
            </label>
            <label class="flex items-center gap-2 text-sm text-muted cursor-pointer">
              <input
                v-model="form.allow_model_fallback"
                type="checkbox"
                class="accent-cyan-400"
                @change="markDirty"
              >
              允许模型降级（无 Key 时使用确定性工作流）
            </label>
          </div>
        </div>
      </div>

      <!-- Presets -->
      <div class="mt-4 flex flex-wrap gap-2">
        <button
          class="button button-ghost text-sm"
          @click="applyPreset('CN')"
        >
          <Globe2 class="h-4 w-4" />
          🇨🇳 CN / CNY / 简中
        </button>
        <button
          class="button button-ghost text-sm"
          @click="applyPreset('US')"
        >
          <Languages class="h-4 w-4" />
          🇺🇸 US / USD / English
        </button>
      </div>

      <!-- Key Status -->
      <div class="mt-5 grid gap-4 lg:grid-cols-2">
        <div class="panel-soft p-4">
          <p class="panel-title">
            密钥状态
          </p>
          <div class="mt-3 grid gap-2 text-sm">
            <div class="flex items-center justify-between rounded-lg border border-slate-700/60 px-3 py-2">
              <span>DeepSeek LLM</span>
              <span :class="['badge', settings?.deepseek_api_key ? 'badge-ok' : 'badge-warn']">{{ settings?.deepseek_api_key ? "已配置 ✓" : "未配置" }}</span>
            </div>
            <div class="flex items-center justify-between rounded-lg border border-slate-700/60 px-3 py-2">
              <span>Steam API</span>
              <span :class="['badge', settings?.steam_api_key ? 'badge-ok' : 'badge-warn']">{{ settings?.steam_api_key ? "已配置 ✓" : "未配置" }}</span>
            </div>
            <div class="flex items-center justify-between rounded-lg border border-slate-700/60 px-3 py-2">
              <span>Firecrawl</span>
              <span :class="['badge', settings?.firecrawl_api_key ? 'badge-ok' : 'badge-warn']">{{ settings?.firecrawl_api_key ? "已配置 ✓" : "未配置" }}</span>
            </div>
          </div>
        </div>

        <div class="panel-soft p-4">
          <p class="panel-title">
            当前值
          </p>
          <div class="mt-3 grid gap-2 text-sm text-muted">
            <div class="flex items-center justify-between">
              <span>默认地区</span><span class="text-slate-200">{{ form.default_cc }}</span>
            </div>
            <div class="flex items-center justify-between">
              <span>默认语言</span><span class="text-slate-200">{{ form.default_language }}</span>
            </div>
            <div class="flex items-center justify-between">
              <span>默认币种</span><span class="text-slate-200">{{ form.default_currency }}</span>
            </div>
            <div class="flex items-center justify-between">
              <span>模型</span><span class="text-slate-200">{{ form.deepseek_model }}</span>
            </div>
            <div class="flex items-center justify-between">
              <span>降级</span><span class="text-slate-200">{{ form.allow_model_fallback ? "允许" : "禁止" }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Auth Token -->
    <div class="mt-5 panel-soft p-4">
      <p class="panel-title">
        身份验证
      </p>
      <p class="mt-1 text-sm text-muted">
        设置后所有 API 请求（除健康检查）都需要携带此 Token。留空则无需认证。
      </p>
      <label class="mt-3 grid gap-1 text-sm text-muted">
        API Token
        <input
          v-model="authToken"
          type="password"
          class="field"
          placeholder="留空则无需认证"
          @input="saveAuthToken"
        >
      </label>
    </div>

    <!-- Collapsible Panels for management tools -->
    <section class="panel p-4">
      <div
        class="collapsible-header"
        @click="toggleSection('monitor')"
      >
        <div>
          <p class="panel-title">
            监控任务
          </p>
          <h2 class="mt-1 text-lg font-semibold">
            定时采集
          </h2>
        </div>
        <ChevronDown
          class="h-4 w-4 text-muted transition-transform"
          :class="collapsedSections.monitor ? 'rotate-180' : ''"
        />
      </div>
      <div
        :class="['collapsible-content', collapsedSections.monitor ? 'collapsed' : '']"
        :style="{ maxHeight: collapsedSections.monitor ? '0px' : '600px' }"
      >
        <MonitorConfig :default-interval="form.collection_interval_minutes" />
      </div>
    </section>

    <section class="panel p-4">
      <div
        class="collapsible-header"
        @click="toggleSection('aliases')"
      >
        <div>
          <p class="panel-title">
            中文别名库
          </p>
          <h2 class="mt-1 text-lg font-semibold">
            游戏别名管理
          </h2>
        </div>
        <ChevronDown
          class="h-4 w-4 text-muted transition-transform"
          :class="collapsedSections.aliases ? 'rotate-180' : ''"
        />
      </div>
      <div
        :class="['collapsible-content', collapsedSections.aliases ? 'collapsed' : '']"
        :style="{ maxHeight: collapsedSections.aliases ? '0px' : '600px' }"
      >
        <GameAliasManager />
      </div>
    </section>

    <section class="panel p-4">
      <div
        class="collapsible-header"
        @click="toggleSection('knowledge')"
      >
        <div>
          <p class="panel-title">
            知识库
          </p>
          <h2 class="mt-1 text-lg font-semibold">
            研究文档
          </h2>
        </div>
        <ChevronDown
          class="h-4 w-4 text-muted transition-transform"
          :class="collapsedSections.knowledge ? 'rotate-180' : ''"
        />
      </div>
      <div
        :class="['collapsible-content', collapsedSections.knowledge ? 'collapsed' : '']"
        :style="{ maxHeight: collapsedSections.knowledge ? '0px' : '600px' }"
      >
        <KnowledgeBasePanel />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from "vue";
import { ChevronDown, Globe2, Languages, Save } from "lucide-vue-next";
import { useSettingsStore } from "@/stores/settings";
import type { AppSettingsRead, AppSettingsUpdate } from "@/api/types";
import GameAliasManager from "@/components/GameAliasManager.vue";
import KnowledgeBasePanel from "@/components/KnowledgeBasePanel.vue";
import MonitorConfig from "@/components/MonitorConfig.vue";

const settingsStore = useSettingsStore();
const saving = ref(false);
const error = ref<string | null>(null);
const successMsg = ref<string | null>(null);
const hasChanges = ref(false);

const form = reactive<AppSettingsUpdate & { collection_interval_minutes: number; default_cc: string; default_language: string; default_currency: string; deepseek_model: string; allow_model_fallback: boolean }>({
  default_cc: "CN", default_language: "schinese", default_currency: "CNY",
  deepseek_model: "deepseek-v4-pro", allow_model_fallback: true, collection_interval_minutes: 60,
});

const settings = ref<AppSettingsRead | null>(null);

const authToken = ref(settingsStore.authToken);
function saveAuthToken() { settingsStore.setAuthToken(authToken.value); }

const collapsedSections = reactive<Record<string, boolean>>({ monitor: false, aliases: false, knowledge: false });
function toggleSection(key: string) { collapsedSections[key] = !collapsedSections[key]; }

function markDirty() { hasChanges.value = true; }

function hydrate() {
  if (!settingsStore.data) return;
  settings.value = settingsStore.data;
  form.default_cc = settingsStore.data.default_cc;
  form.default_language = settingsStore.data.default_language;
  form.default_currency = settingsStore.data.default_currency;
  form.deepseek_model = settingsStore.data.deepseek_model;
  form.allow_model_fallback = settingsStore.data.allow_model_fallback;
  form.collection_interval_minutes = settingsStore.data.collection_interval_minutes;
  hasChanges.value = false;
}

async function save() {
  saving.value = true; error.value = null; successMsg.value = null;
  try {
    settings.value = await settingsStore.save(form);
    hasChanges.value = false;
    successMsg.value = "设置已保存";
    setTimeout(() => { successMsg.value = null; }, 3000);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
  } finally { saving.value = false; }
}

function applyPreset(mode: "CN" | "US") {
  if (mode === "CN") { form.default_cc = "CN"; form.default_language = "schinese"; form.default_currency = "CNY"; }
  else { form.default_cc = "US"; form.default_language = "english"; form.default_currency = "USD"; }
  markDirty();
}

// Warn before leaving with unsaved changes
function beforeUnload(e: BeforeUnloadEvent) {
  if (hasChanges.value) { e.preventDefault(); e.returnValue = ""; }
}
onBeforeUnmount(() => { window.removeEventListener("beforeunload", beforeUnload); });
watch(hasChanges, (v) => {
  if (v) window.addEventListener("beforeunload", beforeUnload);
  else window.removeEventListener("beforeunload", beforeUnload);
});

watch(() => settingsStore.data, () => hydrate(), { immediate: true });
</script>
