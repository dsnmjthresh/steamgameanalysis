import { createRouter, createWebHistory } from "vue-router";

import ChatView from "@/views/ChatView.vue";
import CompareView from "@/views/CompareView.vue";
import DashboardView from "@/views/DashboardView.vue";
import GameDetailView from "@/views/GameDetailView.vue";
import KnowledgeView from "@/views/KnowledgeView.vue";
import SettingsView from "@/views/SettingsView.vue";
import WebSentimentView from "@/views/WebSentimentView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/games/:appid", name: "game", component: GameDetailView, props: true },
    { path: "/compare", name: "compare", component: CompareView },
    { path: "/chat", name: "chat", component: ChatView },
    { path: "/knowledge", name: "knowledge", component: KnowledgeView },
    { path: "/web-sentiment", name: "webSentiment", component: WebSentimentView },
    { path: "/settings", name: "settings", component: SettingsView },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

export default router;
