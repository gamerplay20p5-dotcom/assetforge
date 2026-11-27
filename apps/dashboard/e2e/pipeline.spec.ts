import { expect, test } from "@playwright/test";

// Acceptance flow for Milestone 1, driven through the real UI against a real API + worker.
test("login -> describe -> generate -> queue -> library -> 3D viewer -> download", async ({ page, request }) => {
  await page.goto("/");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/engines$/);
  await expect(page.getByLabel("Motor", { exact: true })).toHaveValue("trellis2-gguf");
  await expect(page.getByLabel("Aplicar decimação na exportação")).not.toBeChecked();
  await expect(page.getByRole("navigation").getByRole("link")).toHaveCount(6);

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

  const href = await page.getByRole("link", { name: "GLB" }).getAttribute("href");
  expect(href).toBeTruthy();
  const download = await request.get(href!, { timeout: 20000 });
  expect(download.ok()).toBeTruthy();
  expect(download.headers()["content-disposition"]).toMatch(/model\.glb/);
  expect((await download.body()).subarray(0, 4).toString()).toBe("glTF");
  await page.goto("about:blank");
});

test("an archived recipe can change only the seed", async ({ page }) => {
  const reference = "ref_a12345678901";
  const recipe = {
    engine: "pixal3d-sv", category: "building", references: { front: reference }, resolution: 1024,
    seed: 7, max_tokens: 38271, texture_size: 4096, structure_guidance: null, shape_guidance: null,
    skip_decimation: false, use_native_threads: true, prepared_inputs: true,
    archive: { worker: "spark", effective_resolution: 1024 },
  };
  await page.route("**/api/v1/assets/ast_replay?version=1", (route) => route.fulfill({ json: {
    id: "ast_replay", name: "Torre", category: "building", manifest: { generation_params: recipe },
  } }));
  await page.route("**/api/v1/workers", (route) => route.fulfill({ json: [{
    id: "wrk_spark", name: "assetforge-spark", online: true, state: "enabled", active_jobs: 0,
    telemetry: {}, capabilities: { features: ["engine.pixal3d-sv", "engine.archive-inputs"] },
  }] }));
  await page.route("**/api/v1/jobs", (route) => route.fulfill({ status: 201, json: { name: "Torre" } }));
  await page.goto("/engines?asset=ast_replay&version=1");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByLabel("Motor", { exact: true })).toHaveValue("pixal3d-sv");
  await expect(page.getByLabel("Seed")).toHaveValue("7");
  await expect(page.getByLabel("Aplicar decimação na exportação")).toBeChecked();
  await expect(page.getByText("Reutilizar esta vista")).toBeVisible();
  await page.getByLabel("Seed").fill("23");
  const request = page.waitForRequest((candidate) => candidate.url().endsWith("/api/v1/jobs") && candidate.method() === "POST");
  await page.getByRole("button", { name: "Enfileirar geração" }).click();
  const body = (await request).postDataJSON();
  const { archive: _archive, ...generation } = recipe;
  expect(body).toEqual({ name: "Torre", asset_id: "ast_replay", worker_id: "wrk_spark",
    job_type: "experimental.reconstruct", params: { ...generation, seed: 23, mesh_scale: 1, three_quarter_angle: 45 } });
  await expect(page.getByRole("link", { name: "Acompanhar Torre" })).toBeVisible();
  await page.goto("about:blank");
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
