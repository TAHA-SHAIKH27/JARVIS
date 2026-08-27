import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    port: 3000,
<<<<<<< Updated upstream
    allowedHosts: [".vercel.run"],
=======
    allowedHosts: true,

>>>>>>> Stashed changes
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  publicDir: 'public',

  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
      },
    },
  },

  worker: {
    format: 'es',
    plugins: () => [],
  },
})