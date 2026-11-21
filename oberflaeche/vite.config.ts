import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// base "./": the app lives under /werkzeug/<projekt>/ (or /vorschau/<projekt>/) – every asset link stays relative.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { proxy: { "/api": "http://127.0.0.1:9999", "/ki": "http://127.0.0.1:9999" } },
});
