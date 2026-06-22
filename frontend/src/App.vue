<template>
  <AppShell>
    <RouterView v-slot="{ Component }">
      <Transition
        name="fade"
        mode="out-in"
      >
        <component :is="Component" />
      </Transition>
    </RouterView>
  </AppShell>
</template>

<script setup lang="ts">
import { onErrorCaptured, ref } from "vue";
import { RouterView } from "vue-router";
import AppShell from "@/components/AppShell.vue";

const error = ref<string | null>(null);

onErrorCaptured((err) => {
  error.value = err instanceof Error ? err.message : "页面渲染出错";
  console.error("App error:", err);
  return false; // prevent propagation
});
</script>
