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
  await expect(rows.first().getByRole("button", { name: "N1" })).toBeVisible();
  await page.getByRole("button", { name: /AFFECTED PAIRS/ }).click();
  await expect(rows.first().getByRole("button", { name: "L1" })).toBeVisible();
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

test("explains hidden inspector selection and restores it when filters clear", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "N1", exact: true }).click();
  await page.getByRole("button", { name: "Lanes", exact: true }).click();
  await expect(page.getByText("The selected element is hidden by the current filters.")).toBeVisible();
  await page.getByRole("button", { name: "clear filters", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Primary supplier" })).toBeVisible();
});

test("offers a recovery action for searches with no matching elements", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Search network elements" }).fill("no-such-element");
  await expect(page.getByText("No matching elements.")).toBeVisible();
  await page.getByRole("button", { name: "Clear filters", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "N1", exact: true })).toBeVisible();
});

test("keeps the dashboard usable when optional element metadata fails", async ({ page }) => {
  await page.unroute("**/api/example/elements");
  await page.route("**/api/example/elements", async (route) => {
    await route.fulfill({ status: 503, body: "unavailable" });
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Element names are temporarily unavailable");
  await expect(page.getByRole("button", { name: "N1", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "N1", exact: true }).click();
  await expect(page.getByRole("heading", { name: "N1" })).toBeVisible();
});

test("rejects invalid network counts rather than displaying misleading metrics", async ({ page }) => {
  await page.unroute("**/api/example/exposure");
  await page.route("**/api/example/exposure", async (route) => {
    await route.fulfill({ json: { ...exposure, nodes: -1 } });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Unexpected analysis response format");
});

test("supports keyboard-only filtering, search reset and element inspection", async ({ page }) => {
  await page.goto("/");
  const lanes = page.getByRole("button", { name: "Lanes", exact: true });
  await lanes.focus();
  await page.keyboard.press("Enter");
  await expect(lanes).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "All", exact: true })).toHaveAttribute("aria-pressed", "false");
  const search = page.getByRole("textbox", { name: "Search network elements" });
  await search.focus();
  await page.keyboard.type("Primary supplier");
  await expect(search).toHaveValue("Primary supplier");
  await page.keyboard.press("Escape");
  await expect(search).toHaveValue("");
  await page.getByRole("button", { name: "All", exact: true }).focus();
  await page.keyboard.press("Enter");
  const supplier = page.getByRole("button", { name: "N1", exact: true });
  await supplier.focus();
  await page.keyboard.press("Enter");
  await expect(supplier).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("complementary", { name: "Element inspector" }).getByRole("heading", { name: "Primary supplier" })).toBeVisible();
});

test("runs an illustrative bounded simulation without disturbing exposure", async ({ page }) => {
  const example = {
    network: { base_currency: "AUD", nodes: [], lanes: [], parts: [], skus: [], customers: [] },
    config: {
      plant_node_id: "demo_plant", sku_id: "demo_sku", component_part_id: "demo_component",
      initial_component_units: 200, initial_finished_units: 5, daily_demand_units: 5,
      horizon_days: 7, production_capacity_per_week: 70, disruption_start_day: 0,
      disruption_duration_days: 7, disruption_severity_fraction: 1, seed: 42
    }
  };
  let posted: unknown = null;
  await page.route("**/api/example/simulation/request", route => route.fulfill({ json: example }));
  await page.route("**/api/simulation/bounded", async route => {
    posted = route.request().postDataJSON();
    await route.fulfill({ json: {
      dataset: "User-supplied network", synthetic: false, element_id: "demo_plant", horizon_days: 7, seed: 42,
      baseline: { total_demand_units: 35, total_fulfilled_units: 15, service_fraction: 15 / 35, daily: [{ day: 0, demand_units: 5, fulfilled_units: 5, backlog_units: 0 }] },
      disrupted: { total_demand_units: 35, total_fulfilled_units: 5, service_fraction: 5 / 35, daily: [{ day: 0, demand_units: 5, fulfilled_units: 5, backlog_units: 0 }] },
      fulfillment_delta_units: -10, assumptions: ["Deterministic demand"], limitations: ["Single component"]
    } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Scenario comparison/ }).click();
  await expect(page.getByRole("heading", { name: "Scenario comparison" })).toBeVisible();
  await page.getByRole("button", { name: "Run comparison" }).click();
  await expect(page.getByRole("region", { name: "Scenario results" })).toContainText("-10 units");
  expect((posted as { config: { horizon_days: number } }).config.horizon_days).toBe(7);
  await page.getByRole("button", { name: /Network exposure/ }).click();
  await expect(page.getByRole("heading", { name: "Structural exposure" })).toBeVisible();
});
