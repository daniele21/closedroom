import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outputDir = process.env.CLOSEDROOM_FRONTEND_OUT_DIR || '../src/local_asr_server/static';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: outputDir,
    emptyOutDir: true,
    // Use hash routing and relative paths so it loads correctly inside WKWebView files or static urls
    assetsDir: 'assets',
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || '1237'}`,
        changeOrigin: true,
      },
      '/v2': {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || '1237'}`,
        changeOrigin: true,
      },
      '/health': {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || '1237'}`,
        changeOrigin: true,
      },
      '/brand': {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || '1237'}`,
        changeOrigin: true,
      },
    },
  },
});