import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname) } },
  test: { exclude: ["e2e/**", "node_modules/**"], environment: "happy-dom", setupFiles: ["./vitest.setup.ts"], globals: true },
});
