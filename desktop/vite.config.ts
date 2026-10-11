import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const sharedConsoleSource = fileURLToPath(
  new URL("../session-console/src", import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@beacon-console": sharedConsoleSource,
    },
    dedupe: ["react", "react-dom"],
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "chrome105",
  },
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
    fs: {
      allow: [".."],
    },
  },
  test: {
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: true,
  },
});
