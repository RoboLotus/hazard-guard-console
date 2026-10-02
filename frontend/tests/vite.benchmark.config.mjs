import { defineConfig, mergeConfig } from 'vite';
import config from '../vite.config.mjs';
export default defineConfig(env => mergeConfig(typeof config==='function'?config(env):config, {
  server:{proxy:{'/ws/bench':{target:(process.env.HAZARD_GUARD_BACKEND_URL || 'http://127.0.0.1:8001').replace(/^http/,'ws'),ws:true}}},
}));
