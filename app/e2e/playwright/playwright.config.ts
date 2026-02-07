import { defineConfig } from '@playwright/test';
import path from 'path';
const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: path.join(__dirname, 'tests'),
  outputDir: path.join(__dirname, 'test-results'),
  timeout: 180000,
  expect: {
    timeout: 15000,
  },
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: {
    baseURL,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on',
  },
  webServer: {
    command: 'node scripts/start-servers.mjs',
    cwd: __dirname,
    url: baseURL,
    timeout: 180000,
    reuseExistingServer: !process.env.CI,
  },
  reporter: [['list'], ['html', { open: 'never' }]],
});
