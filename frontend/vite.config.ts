import react from "@vitejs/plugin-react";

// A bind-mounted source tree on Windows does not deliver inotify events to the
// Linux dev container, so Vite misses edits and keeps serving an old module
// graph. Polling fixes that; it costs CPU, so it is opt-in and only the dev
// compose service turns it on.
const usePolling = process.env.CHOKIDAR_USEPOLLING === "true";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    watch: usePolling ? { usePolling: true, interval: 1000 } : undefined,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    restoreMocks: true,
    exclude: ["**/node_modules/**", "**/dist/**", "tests/e2e-*.spec.ts", "**/*.spec.ts"],
  },
});
