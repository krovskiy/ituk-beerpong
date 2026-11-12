import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  root: 'client',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        bracket: resolve('client/index.html'),
        register: resolve('client/register.html'),
        rules: resolve('client/rules.html'),
        admin: resolve('client/admin/index.html'),
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:3773',
      '/uploads': 'http://127.0.0.1:3773',
    },
  },
});
