import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/*
 * Pinned to localhost:5173 on purpose.
 *
 * The backend's default `CORS_ORIGINS` is exactly `http://localhost:5173`, so
 * serving there means the console works against a freshly started backend with
 * no configuration at all. If you serve on another origin, add it to the
 * backend's `CORS_ORIGINS` or the browser will block every request.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "localhost",
    port: 4173,
    strictPort: true,
  },
});
