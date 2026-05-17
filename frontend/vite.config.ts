import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/api/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
