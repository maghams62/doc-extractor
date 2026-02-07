import {
  test,
  expect,
  openApp,
  uploadDocuments,
  runExtract,
  runAutofill,
  runValidate,
  approveCanonical,
  getRunId,
  readRunJson,
  assertFinalSnapshot,
  assertAutofillNotSubmitted,
  rowByField,
  getRowValue,
  fixturePath,
  stageLocator,
} from '../helpers/e2e-fixtures';

test('E2E human-in-the-loop flow', async ({ page }) => {
  await openApp(page);

  await uploadDocuments(
    page,
    fixturePath('passport_en.png'),
    fixturePath('bad_g28.pdf')
  );

  await runExtract(page);
  const runId = await getRunId(page);

  const blockingBanner = page.locator('.summary-bar').filter({ hasText: 'Blocking' });
  await expect(blockingBanner).toBeVisible();

  const snapshot = await readRunJson(runId, 'final_snapshot.json');
  const summary = snapshot.summary || { red: 0, amber: 0 };
  expect(summary.red + summary.amber).toBeGreaterThan(0);

  const stateRow = await rowByField(page, 'g28.attorney.address.state');
  await expect(stateRow).toBeVisible();
  await stateRow.getByRole('button', { name: 'Edit' }).click();
  const stateInput = stateRow.locator('input');
  await stateInput.fill('CA');
  await stateRow.getByRole('button', { name: 'Save' }).click();
  await expect(stateRow.locator('.source-user')).toBeVisible();
  await expect(stateRow.locator('.chip-locked')).toBeVisible();
  await expect(stateRow.locator('.status-pill.green')).toBeVisible();

  await approveCanonical(page);
  await runAutofill(page);
  await runValidate(page);

  const suggestionItem = page.locator('[data-has-suggestions="true"]').first();
  await expect(suggestionItem).toBeVisible({ timeout: 120000 });
  await suggestionItem.click();

  const aiSuggestion = page.locator('.suggestion-card').filter({ hasText: 'LLM validator' }).first();
  await expect(aiSuggestion, 'Expected at least one LLM suggestion').toBeVisible({ timeout: 120000 });
  await aiSuggestion.scrollIntoViewIfNeeded();
  await aiSuggestion.getByRole('button', { name: 'Apply & lock' }).click();

  const aiRow = aiSuggestion.locator('xpath=ancestor::div[contains(@class,"field-row")]');
  await expect(aiRow.locator('.source-ai')).toBeVisible();
  await expect(aiRow).toContainText('immigration@tryalma.ai');
  await expect(aiRow.locator('.status-pill.green')).toBeVisible();

  const lockedStateValue = await getRowValue(stateRow);

  await approveCanonical(page);
  await page.getByRole('button', { name: 'Re-run autofill' }).click();
  await expect(stageLocator(page, 'Autofill')).toHaveClass(/running/);
  await expect(stageLocator(page, 'Autofill')).toHaveClass(/success/, { timeout: 180000 });

  await runValidate(page);

  const stateRowAfter = await rowByField(page, 'g28.attorney.address.state');
  const lockedStateAfter = await getRowValue(stateRowAfter);
  expect(lockedStateAfter).toBe(lockedStateValue);

  const emailRow = await rowByField(page, 'g28.attorney.email');
  await expect(emailRow).toContainText('immigration@tryalma.ai');

  const finalSnapshot = await assertFinalSnapshot(runId);
  await assertAutofillNotSubmitted(runId);
  const fieldReports = Object.values(finalSnapshot.post_autofill_validation?.fields || {});
  const redFields = fieldReports.filter((field: any) => field.status === 'red');
  expect(redFields.length).toBe(0);
  const nonGreen = fieldReports.filter((field: any) => field.status !== 'green');
  const allowedIssues = new Set([
    'NOT_PRESENT_IN_DOC',
    'EMPTY_REQUIRED',
    'EMPTY_OPTIONAL_PRESENT',
    'AUTOFILL_FAILED',
    'CONFLICT',
  ]);
  expect(nonGreen.every((field: any) => allowedIssues.has(field.issue_type))).toBeTruthy();
});
