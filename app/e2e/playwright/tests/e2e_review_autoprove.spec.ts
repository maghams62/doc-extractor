import {
  test,
  expect,
  openApp,
  uploadDocuments,
  runExtract,
  fixturePath,
} from '../helpers/e2e-fixtures';

test('E2E review auto-approve flow (auth0 signup doc)', async ({ page }) => {
  await openApp(page);

  await uploadDocuments(
    page,
    fixturePath('passport_en.png'),
    fixturePath('auth0_signup.jpg')
  );

  await runExtract(page);

  const autoApprove = page.getByRole('button', { name: /Auto-approve all & continue/i });
  await expect(autoApprove).toBeVisible({ timeout: 120000 });
  await autoApprove.click();

  await expect(
    page.getByText(/Review complete — ready for autofill/i)
  ).toBeVisible({ timeout: 120000 });

  const proceed = page.getByRole('button', { name: /Approve canonical fields/i });
  await expect(proceed).toBeEnabled({ timeout: 120000 });
  await expect(proceed).toContainText(/Proceed to Autofill/i);
  await proceed.click();

  await expect(
    page.getByText(/Ready for autofill — canonical fields approved/i)
  ).toBeVisible({ timeout: 120000 });

  const runAutofillButton = page.getByRole('button', { name: 'Run Autofill' });
  await expect(runAutofillButton).toBeEnabled({ timeout: 120000 });
});
