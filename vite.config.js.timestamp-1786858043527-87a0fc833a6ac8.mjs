// vite.config.js
import { defineConfig } from "file:///C:/Users/taha/OneDrive/Desktop/J.A.R.V.I.S.%20(Claude)/node_modules/vite/dist/node/index.js";
import react from "file:///C:/Users/taha/OneDrive/Desktop/J.A.R.V.I.S.%20(Claude)/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [react()],
  server: {
    port: 3e3,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false
      }
    }
  },
  publicDir: "public",
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        "wake-worker": "src/wake-worker.ts"
      }
    }
  },
  worker: {
    format: "es",
    plugins: () => []
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcuanMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFx0YWhhXFxcXE9uZURyaXZlXFxcXERlc2t0b3BcXFxcSi5BLlIuVi5JLlMuIChDbGF1ZGUpXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFx0YWhhXFxcXE9uZURyaXZlXFxcXERlc2t0b3BcXFxcSi5BLlIuVi5JLlMuIChDbGF1ZGUpXFxcXHZpdGUuY29uZmlnLmpzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9DOi9Vc2Vycy90YWhhL09uZURyaXZlL0Rlc2t0b3AvSi5BLlIuVi5JLlMuJTIwKENsYXVkZSkvdml0ZS5jb25maWcuanNcIjtpbXBvcnQgeyBkZWZpbmVDb25maWcgfSBmcm9tICd2aXRlJ1xuaW1wb3J0IHJlYWN0IGZyb20gJ0B2aXRlanMvcGx1Z2luLXJlYWN0J1xuXG4vLyBodHRwczovL3ZpdGVqcy5kZXYvY29uZmlnL1xuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKHtcbiAgcGx1Z2luczogW3JlYWN0KCldLFxuICBzZXJ2ZXI6IHtcbiAgICBwb3J0OiAzMDAwLFxuICAgIHByb3h5OiB7XG4gICAgICAnL2FwaSc6IHtcbiAgICAgICAgdGFyZ2V0OiAnaHR0cDovLzEyNy4wLjAuMTo4MDAwJyxcbiAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxuICAgICAgICBzZWN1cmU6IGZhbHNlLFxuICAgICAgfVxuICAgIH1cbiAgfSxcbiAgcHVibGljRGlyOiAncHVibGljJyxcbiAgYnVpbGQ6IHtcbiAgICByb2xsdXBPcHRpb25zOiB7XG4gICAgICBpbnB1dDoge1xuICAgICAgICBtYWluOiAnaW5kZXguaHRtbCcsXG4gICAgICAgICd3YWtlLXdvcmtlcic6ICdzcmMvd2FrZS13b3JrZXIudHMnLFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxuICB3b3JrZXI6IHtcbiAgICBmb3JtYXQ6ICdlcycsXG4gICAgcGx1Z2luczogKCkgPT4gW10sXG4gIH0sXG59KSJdLAogICJtYXBwaW5ncyI6ICI7QUFBNFYsU0FBUyxvQkFBb0I7QUFDelgsT0FBTyxXQUFXO0FBR2xCLElBQU8sc0JBQVEsYUFBYTtBQUFBLEVBQzFCLFNBQVMsQ0FBQyxNQUFNLENBQUM7QUFBQSxFQUNqQixRQUFRO0FBQUEsSUFDTixNQUFNO0FBQUEsSUFDTixPQUFPO0FBQUEsTUFDTCxRQUFRO0FBQUEsUUFDTixRQUFRO0FBQUEsUUFDUixjQUFjO0FBQUEsUUFDZCxRQUFRO0FBQUEsTUFDVjtBQUFBLElBQ0Y7QUFBQSxFQUNGO0FBQUEsRUFDQSxXQUFXO0FBQUEsRUFDWCxPQUFPO0FBQUEsSUFDTCxlQUFlO0FBQUEsTUFDYixPQUFPO0FBQUEsUUFDTCxNQUFNO0FBQUEsUUFDTixlQUFlO0FBQUEsTUFDakI7QUFBQSxJQUNGO0FBQUEsRUFDRjtBQUFBLEVBQ0EsUUFBUTtBQUFBLElBQ04sUUFBUTtBQUFBLElBQ1IsU0FBUyxNQUFNLENBQUM7QUFBQSxFQUNsQjtBQUNGLENBQUM7IiwKICAibmFtZXMiOiBbXQp9Cg==
