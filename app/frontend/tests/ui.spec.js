import { test, expect } from "@playwright/test";

const extractResult = {
  run_id: "run_extract",
  result: {
    passport: {
      surname: "DOE",
      given_names: "JANE",
      full_name: "Jane Doe",
      date_of_birth: "1990-01-01",
      date_of_expiration: "2030-01-01",
      sex: "F",
      passport_number: "X1234567",
      place_of_birth: null,
      nationality: null,
      country_of_issue: null,
      date_of_issue: null,
    },
    g28: {
      attorney: {
        family_name: "Doe",
        given_name: "Jane",
        middle_name: null,
        full_name: "Jane Doe",
        law_firm_name: "Doe Law",
        licensing_authority: null,
        bar_number: null,
        email: null,
        phone_daytime: null,
        phone_mobile: null,
        address: {
          street: null,
          unit: null,
          city: null,
          state: "WA",
          zip: "98101",
          country: null,
        },
      },
      client: {
        family_name: null,
        given_name: null,
        middle_name: null,
        full_name: null,
        email: null,
        phone: null,
        address: {
          street: null,
          unit: null,
          city: null,
          state: null,
          zip: null,
          country: null,
        },
      },
    },
    meta: {
      sources: {
        "passport.surname": "OCR",
        "passport.given_names": "OCR",
        "passport.passport_number": "MRZ",
      },
      confidence: {
        "passport.surname": 0.8,
        "passport.given_names": 0.8,
        "passport.passport_number": 0.95,
      },
      status: {},
      evidence: {},
      suggestions: {},
      warnings: [],
    },
  },
};

const verifyResult = {
  run_id: "run_verify",
  result: {
    ...extractResult.result,
    meta: {
      ...extractResult.result.meta,
      status: {
        "passport.surname": "green",
        "passport.given_names": "green",
        "passport.passport_number": "green",
        "g28.attorney.email": "red",
      },
      suggestions: {
        "g28.attorney.email": [
          {
            value: "jane@example.com",
            reason: "LLM suggestion",
            source: "LLM",
            confidence: 0.7,
            evidence: "Email Address (if any) jane@example.com",
          },
        ],
      },
      llm_verification: {
        issues: [
          {
            field: "g28.attorney.email",
            severity: "error",
            message: "Email not found in OCR text.",
            evidence: "",
          },
        ],
        suggestions: {
          "g28.attorney.email": [
            {
              value: "jane@example.com",
              reason: "Recovered from OCR",
              evidence: "jane@example.com",
              confidence: 0.7,
              requires_confirmation: false,
            },
          ],
        },
        summary: "Review missing attorney email.",
      },
    },
  },
  verification: {
    issues: [
      {
        field: "g28.attorney.email",
        severity: "error",
        message: "Email not found in OCR text.",
        evidence: "",
      },
    ],
    suggestions: {
      "g28.attorney.email": [
        {
          value: "jane@example.com",
          reason: "Recovered from OCR",
          evidence: "jane@example.com",
          confidence: 0.7,
          requires_confirmation: false,
        },
      ],
    },
    summary: "Review missing attorney email.",
  },
};

test("verify workflow shows suggestions and applies them", async ({ page }) => {
  await page.route("**/extract", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(extractResult) });
  });
  await page.route("**/verify", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(verifyResult) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Extract" }).click();
  await expect(page.getByText("passport.surname")).toBeVisible();

  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("LLM validator").first()).toBeVisible();

  const emailRow = page.locator(".field-row", { hasText: "g28.attorney.email" });
  await emailRow.getByRole("button", { name: "Apply & lock" }).click();
  await expect(emailRow.locator(".value-text")).toContainText("jane@example.com");

  await expect(emailRow.locator(".value-text")).toContainText("jane@example.com");
});
