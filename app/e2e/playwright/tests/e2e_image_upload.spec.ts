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
  fixturePath,
} from '../helpers/e2e-fixtures';

test('E2E image upload path', async ({ page }) => {
  await openApp(page);

  await uploadDocuments(
    page,
    fixturePath('passport_en.png'),
    fixturePath('bad_g28.png')
  );

  await runExtract(page);
  await approveCanonical(page);
  await runAutofill(page);
  await runValidate(page);

  const runId = await getRunId(page);
  const snapshot = await assertFinalSnapshot(runId);
  await assertAutofillNotSubmitted(runId);

  expect(snapshot.extraction?.passport?.passport_number).toBeTruthy();
  expect(snapshot.extraction?.g28?.attorney?.family_name).toBeTruthy();

  const autofill = snapshot.autofill || {};
  const filledFields = autofill.filled_fields || [];
  expect(filledFields.length).toBeGreaterThan(0);
  expect(autofill.trace_path).toBeTruthy();

  expect(snapshot.post_autofill_validation).toBeTruthy();
});
