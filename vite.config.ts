import { defineConfig } from "vite";
import  dotenv from "dotenv";

dotenv.config();

process.env.NODE_ENV = process.env.NODE_ENV || "development";

export default defineConfig({
  define: {
    ENDPOINT_URL: `"${process.env.ENDPOINT_URL}"`,
  },
  base: '/anxiousbot/',
  build: {
    outDir: 'dist',
    sourcemap: process.env.NODE_ENV === 'development',
    minify: process.env.NODE_ENV !== 'development'
  },
});
