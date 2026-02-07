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
  backendFixturePath,
  fixturePath,
} from '../helpers/e2e-fixtures';

const identityFields = [
  'passport.given_names',
  'passport.surname',
  'passport.passport_number',
  'passport.date_of_birth',
  'passport.date_of_expiration',
  'passport.sex',
];

test('E2E golden path (English docs)', async ({ page }) => {
  await openApp(page);

  await uploadDocuments(
    page,
    fixturePath('passport_en.png'),
    backendFixturePath('Example_G-28.pdf')
  );

  await runExtract(page);

  await expect(await rowByField(page, 'passport.passport_number')).toBeVisible();
  await expect(await rowByField(page, 'g28.attorney.email')).toBeVisible();

  const expectedExtracted = {
    'passport.passport_number': 'L898902C3',
    'passport.given_names': 'Anna Maria',
    'passport.surname': 'Eriksson',
    'g28.attorney.family_name': 'Messi',
    'g28.attorney.given_name': 'Kaka',
    'g28.attorney.email': 'immigration @tryalma.ai',
  };
  for (const [field, expected] of Object.entries(expectedExtracted)) {
    const row = await rowByField(page, field);
    await expect(row).toBeVisible();
    const value = await getRowValue(row);
    const normalize = (val: string) => val.replace(/\s+/g, '').toLowerCase();
    expect(normalize(value)).toBe(normalize(expected));
  }

  const runId = await getRunId(page);

  await approveCanonical(page);
  await runAutofill(page);

  const autofillSummary = await readRunJson(runId, 'autofill_summary.json');
  expect(autofillSummary.attempted_fields?.length || 0).toBeGreaterThan(0);
  expect(Object.keys(autofillSummary.fill_failures || {})).toHaveLength(0);
  const domReadbackValues = Object.values(autofillSummary.dom_readback || {}).filter(
    (value) => value !== null && value !== undefined && String(value).trim() !== ''
  );
  expect(autofillSummary.trace_path, 'Trace path missing').toBeTruthy();
  expect(domReadbackValues.length, 'dom_readback empty').toBeGreaterThan(0);
  if (autofillSummary.final_url) {
    expect(autofillSummary.final_url).not.toMatch(/submit/i);
  }

  await runValidate(page);

  const coverageReport = await readRunJson(runId, 'e2e_coverage_report.json');
  expect(Array.isArray(coverageReport.fields)).toBeTruthy();
  const coverageMap = new Map(coverageReport.fields.map((entry: any) => [entry.field, entry]));
  const passportFields = [
    'passport.given_names',
    'passport.surname',
    'passport.passport_number',
    'passport.date_of_birth',
    'passport.date_of_expiration',
    'passport.sex',
  ];
  const expectedPassport = {
    'passport.given_names': 'Anna Maria',
    'passport.surname': 'Eriksson',
    'passport.passport_number': 'L898902C3',
    'passport.date_of_birth': '1974-08-12',
    'passport.date_of_expiration': '2012-04-15',
    'passport.sex': 'F',
  };
  for (const field of passportFields) {
    const entry = coverageMap.get(field);
    expect(entry, `Missing coverage entry for ${field}`).toBeTruthy();
    expect(entry.autofill_attempted).toBeTruthy();
    expect(entry.autofill_result).toBe('PASS');
    const normalize = (val: string) => val.replace(/\s+/g, '').toLowerCase();
    const expected = expectedPassport[field as keyof typeof expectedPassport];
    expect(normalize(entry.dom_readback_value || '')).toBe(normalize(expected));
  }
  const llmInvokedOnVerified = coverageReport.fields.filter(
    (entry: any) =>
      entry.deterministic_validation_verdict === 'VERIFIED' &&
      entry.llm_validation_invoked
  );
  expect(llmInvokedOnVerified.length).toBe(0);

  const snapshot = await assertFinalSnapshot(runId);
  await assertAutofillNotSubmitted(runId);

  const summary = snapshot.summary || { green: 0, amber: 0, red: 0, requires_human_input: 0 };
  const totalReviewed = summary.green + summary.amber + summary.red;
  expect(summary.green).toBeGreaterThan(totalReviewed / 2);
  expect(summary.requires_human_input).toBe(0);

  for (const field of identityFields) {
    const status = snapshot.resolved_fields?.[field]?.status || 'unknown';
    expect(status, `Identity field ${field} is red`).not.toBe('red');
  }

  const summaryBar = page.locator('.summary-bar').filter({ hasText: 'Blocking' });
  await expect(summaryBar).toBeVisible();

  const suggestionCards = page.locator('.suggestion-card');
  const suggestionCount = await suggestionCards.count();
  for (let i = 0; i < suggestionCount; i += 1) {
    const evidence = await suggestionCards.nth(i).locator('.suggestion-evidence').textContent();
    expect((evidence || '').trim().length).toBeGreaterThan(0);
  }
});
