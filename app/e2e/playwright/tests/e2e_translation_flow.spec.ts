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
  assertFinalSnapshot,
  assertAutofillNotSubmitted,
  getStatusValue,
  backendFixturePath,
  fixturePath,
  waitForRunFile,
} from '../helpers/e2e-fixtures';

test('E2E translation flow (non-English passport)', async ({ page }) => {
  await openApp(page);

  await uploadDocuments(
    page,
    fixturePath('passport_es.png'),
    backendFixturePath('Example_G-28.pdf')
  );

  const detected = page.getByText(/Detected language:/);
  await expect(detected).toBeVisible({ timeout: 120000 });
  const detectedText = (await detected.textContent()) || '';
  expect(detectedText).not.toContain('English');

  const translateButton = page.getByRole('button', { name: 'Translate' });
  await expect(translateButton).toBeVisible();
  await translateButton.click();

  await expect(page.getByText('Translation run')).toBeVisible({ timeout: 180000 });
  const translationRunId = await getStatusValue(page, 'Translation run');
  expect(translationRunId).not.toBe('—');
  await waitForRunFile(translationRunId, 'translated_text.txt');

  await runExtract(page);
  await approveCanonical(page);
  await runAutofill(page);
  await runValidate(page);

  const runId = await getRunId(page);
  const snapshot = await assertFinalSnapshot(runId);
  await assertAutofillNotSubmitted(runId);

  expect(snapshot.extraction?.passport?.passport_number).toBeTruthy();
  expect(snapshot.extraction?.passport?.date_of_birth).toBeTruthy();
  expect(snapshot.extraction?.passport?.date_of_expiration).toBeTruthy();
});
