import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  plugins: [vue(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 3173,
  },
  define: {
    "import.meta.env.VITE_API_BASE_URL": JSON.stringify("http://127.0.0.1:9000/api"),
  },
  test: {
    environment: "jsdom",
    globals: true,
    exclude: ["e2e/**", "node_modules/**"],
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/echarts") || id.includes("node_modules/vue-echarts")) {
            return "echarts";
          }
          if (id.includes("node_modules/shiki")) {
            return "shiki";
          }
          if (
            id.includes("node_modules/vue") ||
            id.includes("node_modules/vue-router") ||
            id.includes("node_modules/pinia")
          ) {
            return "vue";
          }
        },
      },
    },
  },
});
