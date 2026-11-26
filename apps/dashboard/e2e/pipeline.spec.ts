import { expect, test } from "@playwright/test";

// Acceptance flow for Milestone 1, driven through the real UI against a real API + worker.
test("login -> describe -> generate -> queue -> library -> 3D viewer -> download", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Assets gerados")).toBeVisible();

  // wait for the worker to register and heartbeat
  await page.goto("/workers");
  await expect(page.getByText("e2e-cpu").first()).toBeVisible();

  await page.goto("/generator");
  await page.getByLabel("Descrição textual").fill("hospital moderno de cinco andares, 40 x 20 m");
  await page.getByRole("button", { name: "Interpretar" }).click();
  await expect(page.getByText(/Interpretado por/)).toBeVisible();
  await expect(page.locator('input[placeholder="auto"]').nth(2)).toHaveValue("5"); // floors
  await page.getByRole("button", { name: "Gerar asset" }).click();

  await expect(page).toHaveURL(/\/queue/);
  await expect(page.getByText("Concluído").first()).toBeVisible({ timeout: 120_000 });

  await page.goto("/library");
  await page.locator(".card").first().click();
  await expect(page.locator(".viewer canvas")).toBeVisible();
  await expect(page.getByText(/triângulos \(orçamento/)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Wireframe").check();

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "GLB" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/model\.glb$/);
});

test("batch of 10 variations is created and fully processed", async ({ page, request }) => {
  test.setTimeout(420_000);
  await page.goto("/");
  const login = await request.post("/api/v1/auth/login", { data: { username: "admin", password: "e2e-admin-password" } });
  const token = (await login.json()).access_token as string;
  const res = await request.post("/api/v1/batches", {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: "e2e 10", count: 10, seed_start: 500, template: { name: "Casa", params: { category: "house", style: "nordic" } } },
  });
  expect(res.ok()).toBeTruthy();
  const batch = await res.json();
  await expect
    .poll(async () => (await (await request.get(`/api/v1/batches/${batch.id}`, { headers: { Authorization: `Bearer ${token}` } })).json()).counts.succeeded, { timeout: 400_000, intervals: [2000] })
    .toBe(10);
});
