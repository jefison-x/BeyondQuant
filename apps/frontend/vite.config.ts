import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const largeUiComponents = new Set([
  "affix", "alert", "autocomplete", "button", "calendar", "cascader", "date-picker",
  "form", "select-v2", "table", "table-v2", "tree", "tour",
]);

export default defineConfig({
  plugins: [vue()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name(moduleId) {
                const match = moduleId.match(/node_modules\/element-plus\/es\/components\/([^/]+)/);
                if (!match) return null;
                return largeUiComponents.has(match[1]) ? `ui-${match[1]}` : "ui-components";
              },
            },
            { name: "ui-core", test: /node_modules\/(?:element-plus|@element-plus)\// },
            {
              name(moduleId) {
                const match = moduleId.match(/node_modules\/echarts\/lib\/([^/]+)/);
                return match ? `chart-${match[1]}` : null;
              },
            },
            { name: "charts-core", test: /node_modules\/echarts\// },
            { name: "chart-renderer", test: /node_modules\/zrender\// },
            { name: "vue-platform", test: /node_modules\/(?:vue|vue-router|pinia)\// },
          ],
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8100",
        changeOrigin: true,
      },
      "/v1": {
        target: "http://127.0.0.1:8100",
        changeOrigin: true,
      },
    },
  },
});
