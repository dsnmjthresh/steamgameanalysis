<template>
  <section class="panel panel-soft p-4">
    <div class="flex items-start justify-between gap-3">
      <div>
        <p class="panel-title">
          {{ label }}
        </p>
        <p class="mt-2 text-2xl font-semibold tracking-tight text-slate-100">
          {{ value }}
        </p>
      </div>
      <div
        class="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-400/10 text-cyan-300"
      >
        <component
          :is="icon"
          class="h-5 w-5"
        />
      </div>
    </div>
    <p
      v-if="hint"
      class="mt-3 text-sm text-muted"
    >
      {{ hint }}
    </p>
  </section>
</template>

<script setup lang="ts">
import type { Component } from "vue";

defineProps<{
  label: string;
  value: string;
  hint?: string;
  icon: Component;
}>();
</script>
