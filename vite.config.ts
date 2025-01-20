import { defineConfig } from "vite";

export default defineConfig({
  base: '/anxiousbot/',
  build: {
    outDir: 'dist',
    sourcemap: true,
    minify: false
  },
});
