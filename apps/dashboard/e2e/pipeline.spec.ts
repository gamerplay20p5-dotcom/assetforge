import { expect, test } from "@playwright/test";

test("English persists across login and reload without resetting studio inputs", async ({ page }) => {
  await page.goto("/engines");
  const language = page.locator("select.language-select");
  await page.getByLabel("Idioma").selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByLabel("Language")).toHaveValue("en");
  await page.getByLabel("Password").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("link", { name: "3D Reconstruction" })).toBeVisible();

  await page.getByRole("button", { name: "Description", exact: true }).click();
  await page.getByLabel("Describe what you want to create").fill("A wooden bench");
  await language.selectOption("pt-BR");
  await expect(page.getByLabel("Descreva o que quer criar")).toHaveValue("A wooden bench");
  await language.selectOption("en");
  await expect(page.getByLabel("Describe what you want to create")).toHaveValue("A wooden bench");
  await page.getByRole("link", { name: "Infrastructure" }).click();
  await page.getByRole("link", { name: "Queue", exact: true }).click();
  await expect(page.getByRole("button", { name: "All", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Language")).toHaveValue("en");
  await expect(page.getByRole("link", { name: "Library" })).toBeVisible();
});

// Acceptance flow for Milestone 1, driven through the real UI against a real API + worker.
test("login -> describe -> generate -> queue -> library -> 3D viewer -> download", async ({ page, request }) => {
  await page.goto("/");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/engines$/);
  await page.getByText("Ajustes avançados", { exact: true }).click();
  await expect(page.getByLabel("Motor", { exact: true })).toHaveValue("");
  await expect(page.getByRole("region", { name: "Estúdio 3D" }).getByText("Pronto para um novo modelo 3D?")).toBeVisible();
  await page.getByRole("button", { name: "Assets", exact: true }).click();
  await expect(page.getByRole("tab", { name: "Assets", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fechar", exact: true }).click();
  await page.getByRole("button", { name: "Ampliar visualizador" }).click();
  await expect(page.locator(".st-left")).toBeHidden();
  await page.getByRole("button", { name: "Mostrar painel de criação" }).click();
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

test("an archived recipe can change only the seed and use the original studio", async ({ page }) => {
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
  const job = { id: "job_replay", name: "Torre", asset_id: "ast_replay", asset_version: 2, params: recipe };
  let completed = false;
  await page.route("**/api/v1/jobs", (route) => route.fulfill({ status: 201, json: { ...job, status: "queued", progress: 0 } }));
  await page.route("**/api/v1/jobs/job_replay", (route) => route.fulfill({ json: {
    ...job, status: completed ? "succeeded" : "running", progress: completed ? 1 : 0.42, current_stage: "surface",
  } }));
  await page.route("**/api/v1/assets/ast_replay?version=2", (route) => route.fulfill({ json: {
    id: "ast_replay", name: "Torre", current_version: 2, version_info: { version: 2 },
    triangle_count: 100, manifest: { lods: [] }, files: [],
  } }));
  await page.route("**/api/v1/assets/ast_replay/files/model.glb?*", (route) => route.abort());
  await page.goto("/engines?asset=ast_replay&version=1");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByLabel("Motor", { exact: true })).toHaveValue("pixal3d-sv");
  await expect(page.getByLabel("Seed")).toHaveValue("7");
  await expect(page.getByText("A receita original inclui decimação.")).toBeVisible();
  await expect(page.getByText("Reutilizar esta vista")).toBeVisible();
  await page.getByLabel("Seed").fill("23");
  const request = page.waitForRequest((candidate) => candidate.url().endsWith("/api/v1/jobs") && candidate.method() === "POST");
  await page.getByRole("button", { name: "Gerar modelo" }).click();
  const body = (await request).postDataJSON();
  const { archive: _archive, ...generation } = recipe;
  expect(body).toEqual({ name: "Torre", asset_id: "ast_replay", worker_id: "wrk_spark",
    job_type: "experimental.reconstruct", params: { ...generation, seed: 23, mesh_scale: 1, three_quarter_angle: 45 } });
  await expect(page.getByRole("link", { name: "Acompanhar Torre" })).toBeVisible();
  await expect(page).toHaveURL(/job=job_replay/);
  await expect(page.locator(".st-gen .gen-anim canvas")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Progresso da geração" })).toHaveAttribute("aria-valuenow", "42");
  await page.reload();
  await expect(page.getByText("Gerando a superfície e as texturas")).toBeVisible();
  completed = true;
  await expect(page.locator(".st-stage .viewer")).toBeVisible();
  await expect(page.getByRole("link", { name: "GLB" })).toHaveAttribute("href", /version=2/);
  await page.goto("about:blank");
});

test("the studio shows the reference job and reconstruction on the same stage", async ({ page }) => {
  await page.route("**/api/v1/workers", (route) => route.fulfill({ json: [{
    id: "wrk_spark", name: "Spark", online: true, state: "enabled", telemetry: {},
    capabilities: { features: ["engine.trellis2-gguf", "engine.split-reference"] },
  }] }));
  let referenceDone = false;
  await page.route("**/api/v1/studio/text*", (route) => route.fulfill({ status: 201, json: { name: "Máquina retrô", id: "job_text" } }));
  await page.route("**/api/v1/jobs/job_text", (route) => route.fulfill({ json: {
    id: "job_text", name: "Máquina retrô", status: referenceDone ? "running" : "queued", progress: 0.4,
    current_stage: referenceDone ? "inference" : null, params: { reference_job_id: "job_ref" },
  } }));
  await page.route("**/api/v1/jobs/job_ref", (route) => route.fulfill({ json: {
    id: "job_ref", worker_id: "wrk_spark", status: referenceDone ? "succeeded" : "running",
    progress: referenceDone ? 1 : 0.3, current_stage: "text_to_image",
  } }));
  await page.goto("/engines");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("button", { name: "Múltiplas vistas" }).click();
  await expect(page.getByLabel("Vista 3/4", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Descrição" }).click();
  await page.getByLabel("Descreva o que quer criar").fill("Máquina retrô azul com botões laranja");
  const request = page.waitForRequest((candidate) => new URL(candidate.url()).pathname === "/api/v1/studio/text" && candidate.method() === "POST");
  await page.getByRole("button", { name: "Gerar modelo" }).click();
  expect((await request).postDataJSON().params).toMatchObject({ prompt: "Máquina retrô azul com botões laranja", references: {}, skip_decimation: true });
  await expect(page).toHaveURL(/job=job_text$/);
  await expect(page.getByText("Criando a imagem de referência")).toBeVisible();
  await expect(page.locator(".st-gen canvas")).toBeVisible();
  referenceDone = true;
  await expect(page.getByText("Reconstruindo o modelo")).toBeVisible();
  await page.goto("about:blank");
});

test("regeneration uses the saved reference job ID without uploading again", async ({ page }) => {
  const referenceJobId = "job_0123456789ab";
  await page.route("**/api/v1/assets/ast_saved?version=1", (route) => route.fulfill({ json: {
    id: "ast_saved", name: "Lanterna", category: "prop",
    manifest: { generation_params: { engine: "trellis2-gguf", resolution: 512, reference_job_id: referenceJobId,
      references: { front: "ref_0123456789ab" } } },
  } }));
  await page.route("**/api/v1/references/batch", () => { throw new Error("Regeneration should reuse the saved PNG"); });
  await page.route("**/api/v1/jobs", (route) => route.fulfill({ status: 201, json: { name: "Lanterna", id: "job_regenerated" } }));
  await page.goto("/engines?asset=ast_saved&version=1");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByText("Reutilizar esta vista")).toBeVisible();
  await page.getByLabel("Seed").fill("7");
  const request = page.waitForRequest((candidate) => candidate.url().endsWith("/api/v1/jobs") && candidate.method() === "POST");
  await page.getByRole("button", { name: "Gerar modelo", exact: true }).click();
  expect((await request).postDataJSON().params).toMatchObject({
    reference_job_id: referenceJobId, references: {}, resolution: 512, seed: 7, skip_decimation: true,
  });
});

test("references can be removed and selected again", async ({ page }) => {
  const file = (name: string) => ({
    name, mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB6sAAAAASUVORK5CYII=", "base64"),
  });
  await page.goto("/engines");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  const front = page.getByLabel("Frente", { exact: true });
  const submit = page.getByRole("button", { name: "Gerar modelo" });
  await front.setInputFiles(file("frente.png"));
  await expect(submit).toBeEnabled();
  await page.getByRole("button", { name: "Remover imagem: Frente" }).click();
  await expect(submit).toBeDisabled();
  await front.setInputFiles(file("frente.png"));
  await expect(submit).toBeEnabled();
  await page.getByLabel("Enviar em lote").check();
  const batch = page.getByLabel("Referências do lote");
  await batch.setInputFiles([file("primeira.png"), file("segunda.png")]);
  await page.getByRole("button", { name: "Remover primeira.png" }).click();
  await expect(page.getByText("1 imagem selecionada")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remover segunda.png" })).toBeVisible();
  await page.getByRole("button", { name: "Limpar lote" }).click();
  await expect(submit).toBeDisabled();
  await batch.setInputFiles(file("segunda.png"));
  await expect(submit).toBeEnabled();
  await page.goto("about:blank");
});

test("multi-view submission keeps the selected resolution and every view", async ({ page }) => {
  await page.route("**/api/v1/references/batch", async (route) => {
    const data = route.request().postData() ?? "";
    for (const file of ["front", "right", "back", "angle"]) expect(data).toContain(`filename="${file}.png"`);
    await route.fulfill({ json: { items: ["1", "2", "3", "4"].map((suffix) => ({ id: `ref_00000000000${suffix}` })) } });
  });
  await page.route("**/api/v1/jobs", (route) => route.fulfill({ status: 201, json: { name: "Vista de teste", id: "job_views" } }));
  await page.goto("/engines");
  await page.getByLabel("Senha").fill("e2e-admin-password");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("button", { name: "Múltiplas vistas" }).click();
  const submit = page.getByRole("button", { name: "Gerar modelo", exact: true });
  for (const [view, file] of [["Frente", "front"], ["Lateral direita", "right"], ["Costas", "back"], ["Vista 3/4", "angle"]]) {
    await expect(submit).toBeDisabled();
    await page.getByLabel(view, { exact: true }).setInputFiles({
      name: `${file}.png`, mimeType: "image/png",
      buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB6sAAAAASUVORK5CYII=", "base64"),
    });
  }
  await page.getByText("Ajustes avançados", { exact: true }).click();
  await page.getByLabel("Motor", { exact: true }).selectOption("pixal3d-mv");
  await page.getByLabel("Resolução").selectOption("1536");
  const request = page.waitForRequest((candidate) => candidate.url().endsWith("/api/v1/jobs") && candidate.method() === "POST");
  await submit.click();
  expect((await request).postDataJSON().params).toMatchObject({
    engine: "pixal3d-mv", resolution: 1536, skip_decimation: true,
    references: { front: "ref_000000000001", right: "ref_000000000002", back: "ref_000000000003", three_quarter: "ref_000000000004" },
  });
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
