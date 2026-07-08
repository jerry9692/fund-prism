import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // Vite 默认不向 process.env 注入 VITE_ 变量，需要手动 load
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.FUND_PRISM_API_URL || env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
  };
});
