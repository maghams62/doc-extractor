import { test as base, expect } from '@playwright/test';
import fs from 'fs';
import fsp from 'fs/promises';
import path from 'path';

const REPO_ROOT = path.resolve(__dirname, '../../../..');
const BACKEND_RUNS_DIR = path.join(REPO_ROOT, 'app', 'backend', 'runs');
const FIXTURES_DIR = path.join(REPO_ROOT, 'app', 'e2e', 'playwright', 'fixtures');
const BACKEND_FIXTURES_DIR = path.join(REPO_ROOT, 'app', 'backend', 'tests', 'fixtures');
const API_PORT = process.env.E2E_BACKEND_PORT || '8000';
const API_HOST = process.env.E2E_API_HOST || '127.0.0.1';
const API_BASE = `http://${API_HOST}:${API_PORT}`;

export const paths = {
  repoRoot: REPO_ROOT,
  backendRunsDir: BACKEND_RUNS_DIR,
  fixturesDir: FIXTURES_DIR,
  backendFixturesDir: BACKEND_FIXTURES_DIR,
  apiBase: API_BASE,
};

export function fixturePath(name: string): string {
  const localPath = path.join(FIXTURES_DIR, name);
  if (fs.existsSync(localPath)) {
    return localPath;
  }
  return path.join(REPO_ROOT, name);
}

export function backendFixturePath(name: string): string {
  return path.join(BACKEND_FIXTURES_DIR, name);
}

export function stageLocator(page, label: string) {
  return page.locator('.stepper .step').filter({ hasText: label });
}

export async function openApp(page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Passport \+ G-28 extraction/i })).toBeVisible();
}

export async function uploadDocuments(page, passportPath: string, g28Path: string) {
  await page.setInputFiles('#passport-input', passportPath);
  await page.setInputFiles('#g28-input', g28Path);
}

export async function runExtract(page) {
  await page.getByRole('button', { name: 'Run extraction' }).click();
  await expect(page.getByText(/Run ID:/)).toBeVisible({ timeout: 120000 });
  await expect(stageLocator(page, 'Extract & Review')).toHaveClass(/running|success/, { timeout: 120000 });
}

export async function runAutofill(page) {
  await page.getByRole('button', { name: 'Run Autofill' }).click();
  await expect(stageLocator(page, 'Autofill')).toHaveClass(/success/, { timeout: 180000 });
  await expect(page.getByText('Autofill run')).toBeVisible({ timeout: 180000 });
}

export async function runValidate(page) {
  await page.getByRole('button', { name: 'Run Validation' }).click();
  await expect(stageLocator(page, 'Validate')).toHaveClass(/success/, { timeout: 180000 });
  await expect(page.getByText('Validation run')).toBeVisible({ timeout: 180000 });
}

export async function approveCanonical(page) {
  const button = page.getByRole('button', { name: /Approve canonical fields/i });
  await expect(button).toBeVisible({ timeout: 120000 });
  await expect(button).toBeEnabled({ timeout: 120000 });
  await button.click();
}

export async function getRunId(page): Promise<string> {
  const text = await page.locator('p.run').textContent();
  const match = /Run ID:\s*(\S+)/.exec(text || '');
  if (!match) {
    throw new Error('Run ID not found');
  }
  return match[1];
}

export async function getStatusValue(page, label: string): Promise<string> {
  const block = page.locator('.status-grid > div').filter({ hasText: label }).first();
  await expect(block).toBeVisible();
  const value = await block.locator('.status-value').textContent();
  return (value || '').trim();
}

export async function rowByField(page, fieldPath: string) {
  const queueItem = page.locator(`[data-queue-field="${fieldPath}"]`).first();
  if (await queueItem.count()) {
    await queueItem.scrollIntoViewIfNeeded();
    await queueItem.click();
  } else {
    await page.getByRole('button', { name: /All fields/i }).click();
    const fallback = page.locator(`[data-queue-field="${fieldPath}"]`).first();
    await fallback.scrollIntoViewIfNeeded();
    await fallback.click();
  }
  return page.locator(`[data-detail-field="${fieldPath}"]`).first();
}

export async function getRowValue(row): Promise<string> {
  const input = row.locator('input');
  if (await input.count()) {
    return (await input.inputValue()).trim();
  }
  const value = await row.locator('.value-text').first().textContent();
  return (value || '').trim();
}

export async function waitForRunFile(runId: string, filename: string): Promise<string> {
  const filePath = path.join(BACKEND_RUNS_DIR, runId, filename);
  await expect
    .poll(() => fs.existsSync(filePath), { timeout: 180000 })
    .toBe(true);
  return filePath;
}

export async function readRunJson(runId: string, filename: string): Promise<any> {
  const filePath = await waitForRunFile(runId, filename);
  const raw = await fsp.readFile(filePath, 'utf-8');
  return JSON.parse(raw);
}

export async function assertFinalSnapshot(runId: string): Promise<any> {
  const snapshot = await readRunJson(runId, 'final_snapshot.json');
  expect(snapshot).toHaveProperty('extraction');
  expect(snapshot).toHaveProperty('autofill');
  expect(snapshot).toHaveProperty('post_autofill_validation');
  expect(snapshot).toHaveProperty('resolved_fields');
  expect(snapshot).toHaveProperty('summary');
  const summary = snapshot.summary || {};
  expect(summary).toHaveProperty('green');
  expect(summary).toHaveProperty('amber');
  expect(summary).toHaveProperty('red');
  expect(summary).toHaveProperty('requires_human_input');
  return snapshot;
}

export async function assertAutofillNotSubmitted(runId: string): Promise<any> {
  const summary = await readRunJson(runId, 'autofill_summary.json');
  const finalUrl = (summary.final_url || '').toString();
  if (finalUrl) {
    expect(finalUrl).not.toMatch(/submit/i);
  }
  return summary;
}

async function copyIfExists(source: string, dest: string) {
  try {
    await fsp.copyFile(source, dest);
    return true;
  } catch (error) {
    return false;
  }
}

async function readRunIdFromPage(page): Promise<string | null> {
  try {
    const locator = page.locator('p.run');
    if (!(await locator.count())) return null;
    const text = await locator.first().textContent();
    const match = /Run ID:\s*(\S+)/.exec(text || '');
    return match ? match[1] : null;
  } catch (error) {
    return null;
  }
}

export const test = base.extend<{ consoleErrors: string[]; serverErrors: string[] }>({
  consoleErrors: async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => {
      errors.push(`pageerror: ${error.message || error}`);
    });
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(`console.${msg.type()}: ${msg.text()}`);
      }
    });
    await use(errors);
  },
  serverErrors: async ({ page }, use) => {
    const errors: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if (!url.startsWith(API_BASE)) return;
      if (response.status() >= 500) {
        errors.push(`${response.status()} ${response.request().method()} ${url}`);
      }
    });
    await use(errors);
  },
});

export { expect };

test.afterEach(async ({ page, consoleErrors, serverErrors }, testInfo) => {
  if (consoleErrors.length) {
    await testInfo.attach('console-errors', {
      body: consoleErrors.join('\n'),
      contentType: 'text/plain',
    });
  }
  if (serverErrors.length) {
    await testInfo.attach('backend-5xx', {
      body: serverErrors.join('\n'),
      contentType: 'text/plain',
    });
  }

  if (testInfo.status !== testInfo.expectedStatus) {
    const runId = await readRunIdFromPage(page);
    if (runId) {
      const runDir = path.join(BACKEND_RUNS_DIR, runId);
      const runLog = path.join(runDir, 'run.log');
      const snapshot = path.join(runDir, 'final_snapshot.json');
      const outRunLog = testInfo.outputPath('run.log');
      const outSnapshot = testInfo.outputPath('final_snapshot.json');
      if (await copyIfExists(runLog, outRunLog)) {
        await testInfo.attach('run.log', { path: outRunLog, contentType: 'text/plain' });
      }
      if (await copyIfExists(snapshot, outSnapshot)) {
        await testInfo.attach('final_snapshot.json', { path: outSnapshot, contentType: 'application/json' });
      }
    }
  } else {
    const screenshotPath = testInfo.outputPath('final.png');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await testInfo.attach('final.png', { path: screenshotPath, contentType: 'image/png' });
  }

  expect(consoleErrors, 'Console errors detected').toEqual([]);
  expect(serverErrors, 'Backend 5xx responses detected').toEqual([]);
});
