import { test, expect } from "@playwright/test";

const exposure = {
  dataset: "Moreton Marine Systems",
  synthetic: true,
  method: "Structural dependency screen",
  limitations: "No inventory or delivery timing",
  nodes: 2,
  lanes: 1,
  rows: [
    { element_id: "N1", element_type: "node", convergence_fraction: 0.8, affected_customer_sku_pairs: 4 },
    { element_id: "L1", element_type: "lane", convergence_fraction: 0.2, affected_customer_sku_pairs: 1 },
    { element_id: "N2", element_type: "node", convergence_fraction: 0.4, affected_customer_sku_pairs: 2 },
  ],
};

const elements = {
  nodes: [{ id: "N1", name: "Primary supplier" }, { id: "N2", name: "Assembly plant" }],
  lanes: [{ id: "L1", origin_id: "N1", destination_id: "N2" }],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/example/exposure", async (route) => {
    await route.fulfill({ json: exposure });
  });
  await page.route("**/api/example/elements", async (route) => {
    await route.fulfill({ json: elements });
  });
});

test("renders the synthetic network and allows searching, filtering and inspection", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Structural exposure" })).toBeVisible();
  await expect(page.getByText("Primary supplier", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Lanes", exact: true }).click();
  await expect(page.getByRole("button", { name: "L1", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "N1", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page.getByRole("textbox", { name: "Search network elements" }).fill("Assembly plant");
  await expect(page.getByRole("button", { name: "N2", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "N1", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "N2", exact: true }).click();
  await expect(page.getByRole("complementary").last().getByRole("heading", { name: "Assembly plant" })).toBeVisible();
});

test("sorts exposure and pair counts independently", async ({ page }) => {
  await page.goto("/");
  const rows = page.locator("tbody tr");
  await expect(rows.first().getByRole("button", { name: "N1" })).toBeVisible();
  await page.getByRole("button", { name: /AFFECTED PAIRS/ }).click();
  await expect(rows.first().getByRole("button", { name: "L1" })).toBeVisible();
  await page.getByRole("button", { name: /AFFECTED PAIRS/ }).click();
  await expect(rows.first().getByRole("button", { name: "N1" })).toBeVisible();
});

test("shows a retryable error for invalid API responses", async ({ page }) => {
  await page.unroute("**/api/example/exposure");
  await page.route("**/api/example/exposure", async (route) => {
    await route.fulfill({ json: { rows: [] } });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Unexpected analysis response format");
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
});

test("fits narrow mobile screens without page-wide horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Structural exposure" })).toBeVisible();
  await expect(page.getByRole("button", { name: "N1", exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});
