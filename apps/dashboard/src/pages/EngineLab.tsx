import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote } from "../components/ui";
import type { Asset, Job, Worker } from "../types";
import { Studio } from "./Studio";

interface Engine {
  id: string;
  label: string;
  resolutions: number[];
  views: string[];
  experimental: boolean;
  commercial_status: string;
}

const views: Record<string, string> = { front: "Frente", right: "Lateral direita", back: "Costas", three_quarter: "Vista 3/4" };

interface Recipe {
  engine?: string;
  resolution?: number;
  max_tokens?: number;
  texture_size?: number;
  seed?: number;
  structure_guidance?: number | null;
  shape_guidance?: number | null;
  three_quarter_angle?: number;
  mesh_scale?: number;
  skip_decimation?: boolean;
  use_native_threads?: boolean;
  prepared_inputs?: boolean;
  archived_projection?: { camera_angle_x: number; transforms: Record<string, number[][]> };
  archive_azimuth_override?: number;
  references?: Record<string, string>;
  original_references?: Record<string, string>;
  archive?: { worker: string; effective_resolution: number | null; replay_issue?: string };
}

function groupBatch(files: File[], required: string[]) {
  const groups = new Map<string, Record<string, File>>();
  for (const file of files) {
    const stem = file.name.replace(/\.[^.]+$/, "");
    const match = stem.match(/^(.+)__(front|right|back|three_quarter)$/i);
    if (!match && required.length > 1) throw new Error(`Identifique a vista no nome de ${file.name}.`);
    const name = match?.[1] ?? stem;
    const view = match?.[2].toLowerCase() ?? "front";
    if (!required.includes(view)) throw new Error(`A vista ${view} de ${name} não é usada por este motor.`);
    const refs = groups.get(name) ?? {};
    if (refs[view]) throw new Error(`${name} tem mais de um arquivo para a vista ${views[view]}.`);
    refs[view] = file;
    groups.set(name, refs);
  }
  return [...groups].map(([name, files]) => ({ name, files }));
}

export function EngineLab() {
  const [query] = useSearchParams();
  const assetId = query.get("asset");
  const sourceVersion = query.get("version");
  const source = useQuery({
    queryKey: ["asset", assetId, sourceVersion],
    queryFn: () => api<Asset>(`/assets/${encodeURIComponent(assetId!)}${sourceVersion ? `?version=${encodeURIComponent(sourceVersion)}` : ""}`),
    enabled: !!assetId,
  });
  if (source.error) return <ErrorNote error={source.error} />;
  if (assetId && !source.data) return <p>Carregando receita…</p>;
  return <Studio reconstructionControls={(onCreated) =>
    <ReconstructionForm key={`${assetId ?? ""}:${sourceVersion ?? ""}`} source={source.data} onCreated={onCreated} />} />;
}

function ReconstructionForm({ source, onCreated }: { source?: Asset; onCreated: (jobId: string) => void }) {
  const assetId = source?.id;
  const recipe = source?.manifest?.generation_params as Recipe | undefined;
  const cache = useQueryClient();
  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api<{ items: Engine[] }>("/engines") });
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 15000 });
  const [engineId, setEngine] = useState(recipe?.engine ?? "trellis2-gguf");
  const [name, setName] = useState(source?.name ?? "");
  const [categoryOverride, setCategory] = useState("");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [workerId, setWorker] = useState<string>();
  const [resolution, setResolution] = useState(recipe?.resolution ?? 1024);
  const [tokens, setTokens] = useState(recipe?.max_tokens ?? 49152);
  const [texture, setTexture] = useState(recipe?.texture_size ?? 4096);
  const [seed, setSeed] = useState(recipe?.seed ?? 1);
  const [structure, setStructure] = useState(recipe?.structure_guidance === undefined ? 7.5 : recipe.structure_guidance);
  const [shape, setShape] = useState(recipe?.shape_guidance === undefined ? 7.5 : recipe.shape_guidance);
  const [angle, setAngle] = useState(recipe?.three_quarter_angle ?? 45);
  const [scale, setScale] = useState(recipe?.mesh_scale ?? 1);
  const [skipDecimation, setSkipDecimation] = useState(recipe?.skip_decimation ?? true);
  const [batchMode, setBatchMode] = useState(false);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const category = categoryOverride || source?.category || "building";
  const sameEngine = recipe?.engine === engineId;
  const usePrepared = !!(sameEngine && recipe?.prepared_inputs && !Object.keys(files).length);
  const archivedProjection = usePrepared ? recipe?.archived_projection : undefined;
  const existing = sameEngine && (!recipe?.prepared_inputs || usePrepared) ? recipe?.references : recipe?.original_references ?? recipe?.references;
  const engine = engines.data?.items.find((item) => item.id === engineId);
  const compatible = (workers.data ?? []).filter((worker) =>
    worker.capabilities.features?.includes(`engine.${engineId}`));
  const historicalWorker = compatible.find((w) => {
    const name = w.name.toLowerCase();
    return recipe?.archive?.worker === "spark" ? name.includes("spark") : recipe?.archive?.worker === "4090" && name.includes("4090");
  });
  const selectedWorker = compatible.find((worker) => worker.id === (workerId ?? historicalWorker?.id));
  const unavailable = !!selectedWorker && (!selectedWorker.online || selectedWorker.state !== "enabled");
  const create = useMutation({
    mutationFn: async () => {
      if (!engine || unavailable) throw new Error("Selecione um motor e um worker disponível.");
      const groups = batchMode ? groupBatch(batchFiles, engine.views) : [{ name: name.trim(), files }];
      if (!groups.length) throw new Error("Selecione os arquivos do lote.");
      const form = new FormData();
      const assignments: { group: number; view: string }[] = [];
      const refs = groups.map((): Record<string, string> => ({}));
      for (const [index, group] of groups.entries()) {
        if (group.name.length > 120) throw new Error(`Nome de asset muito longo: ${group.name}`);
        for (const view of engine.views) {
          const file = group.files[view];
          if (file) {
            form.append("files", file);
            assignments.push({ group: index, view });
          } else if (!batchMode && existing?.[view]) refs[index][view] = existing[view];
          else throw new Error(`Envie a vista ${views[view]} de ${group.name}.`);
        }
      }
      if (assignments.length) {
        const saved = await api<{ items: { id: string }[] }>("/references/batch", { method: "POST", body: form });
        for (const [index, { group, view }] of assignments.entries()) refs[group][view] = saved.items[index].id;
      }
      const items = groups.map((group, index) => ({
        name: group.name, asset_id: assetId ?? undefined, worker_id: selectedWorker?.id,
        job_type: "experimental.reconstruct",
        params: { engine: engineId, category, references: refs[index], resolution, max_tokens: tokens,
          seed, texture_size: texture, structure_guidance: structure, shape_guidance: shape,
          mesh_scale: scale, three_quarter_angle: angle, skip_decimation: skipDecimation,
          prepared_inputs: usePrepared, use_native_threads: !!(sameEngine && recipe?.use_native_threads),
          archived_projection: archivedProjection,
          archive_azimuth_override: archivedProjection && angle !== recipe?.three_quarter_angle ? angle
            : archivedProjection ? recipe?.archive_azimuth_override : undefined },
      }));
      if (batchMode) {
        const batch = await api<{ id: string; name: string; total: number }>("/batches", { method: "POST", json: { name: name.trim(), items } });
        const recent = await api<{ items: Job[] }>(`/jobs?batch_id=${encodeURIComponent(batch.id)}&limit=1`).catch(() => null);
        return { jobId: recent?.items[0]?.id, label: `${batch.name} · ${batch.total} gerações`, route: "/batch" };
      }
      const job = await api<Job>("/jobs", { method: "POST", json: items[0] });
      return { jobId: job.id, label: job.name, route: "/queue" };
    },
    onSuccess: (result) => {
      if (result.jobId) onCreated(result.jobId);
      cache.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return <div className="st-engine">
      <div className="st-title"><Sparkles size={16} /> {assetId ? "Repetir geração" : "Gerar modelo 3D"}</div>
      {recipe?.archive && <div className="st-hint">
        Experimento na {recipe.archive.worker === "4090" ? "RTX 4090" : "DGX Spark"}.
        Resolução efetiva anterior {recipe.archive.effective_resolution ?? "não registrada"}.
        {recipe.archive.replay_issue && ` ${recipe.archive.replay_issue}`}
        {unavailable && " O worker original está indisponível. Selecione outro worker para continuar."}
      </div>}
      <div className="form-grid">
        <label>Motor<select aria-label="Motor" value={engineId} onChange={(e) => {
          const next = engines.data?.items.find((item) => item.id === e.target.value);
          if (!next) return;
          setEngine(next.id);
          if (!next.resolutions.includes(resolution)) setResolution(next.resolutions[0]);
          if (!recipe && tokens === 49152 && next.id === "pixal3d-python") setTokens(131072);
          setWorker("");
          setFiles({});
          create.reset();
        }}>
          {engines.data?.items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select></label>
      </div>
      <div className="st-hint">Experimental · licença comercial pendente</div>
      {engines.error && <ErrorNote error={engines.error} />}
      {engine && <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} onInvalidCapture={(e) => {
        (e.target as HTMLElement).closest("details")?.setAttribute("open", "");
      }}>
        <div className="form-grid">
          {!assetId && <label>Envio<select value={batchMode ? "batch" : "single"} onChange={(e) => setBatchMode(e.target.value === "batch")}>
            <option value="single">Um asset</option><option value="batch">Lote de assets</option>
          </select></label>}
          <label>{batchMode ? "Nome do lote" : "Nome"}<input value={name} required maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
          <label>Categoria<select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="building">Construção</option><option value="vehicle">Veículo</option>
            <option value="npc">NPC</option><option value="prop">Objeto</option>
          </select></label>
          <label>Resolução solicitada<select value={resolution} onChange={(e) => setResolution(Number(e.target.value))}>
            {engine.resolutions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select></label>
          <label>Textura (px)<select value={texture} onChange={(e) => setTexture(Number(e.target.value))}>
            {[512, 1024, 2048, 4096, 8192, 16384].map((item) => <option key={item} value={item}>{item}</option>)}
          </select></label>
        </div>
        <details open={source ? true : undefined}>
          <summary>Ajustes avançados</summary>
          <div className="form-grid">
          <label>Orçamento de tokens<input type="number" min={1} value={tokens} required onChange={(e) => setTokens(Number(e.target.value))} /></label>
          <label>Seed<input type="number" min={0} value={seed} required onChange={(e) => setSeed(Number(e.target.value))} /></label>
          <label>Guidance da estrutura<input type="number" min={0} max={32} step={0.1} placeholder="Padrão do motor"
            value={structure ?? ""} onChange={(e) => setStructure(e.target.value === "" ? null : Number(e.target.value))} /></label>
          <label>Guidance da forma<input type="number" min={0} max={32} step={0.1} placeholder="Padrão do motor"
            value={shape ?? ""} onChange={(e) => setShape(e.target.value === "" ? null : Number(e.target.value))} /></label>
          <label className="check">
            <input type="checkbox" checked={!skipDecimation} onChange={(e) => setSkipDecimation(!e.target.checked)} />
            Aplicar decimação na exportação
          </label>
          {engine.views.length > 1 && <>
            <label>Azimute da vista 3/4 (°)<input type="number" min={1} max={359} step={0.1} required value={angle} onChange={(e) => setAngle(Number(e.target.value))} /></label>
            <label>Escala de projeção<input type="number" min={0.01} max={10} step={0.01} required value={scale} onChange={(e) => setScale(Number(e.target.value))} /></label>
          </>}
          </div>
        </details>
        <h3>Referências</h3>
        <p className="muted">PNG, JPEG ou WebP. O worker remove o fundo e alinha o enquadramento quando necessário.</p>
        {usePrepared && <p className="muted">A receita reutiliza as entradas preparadas. Se enviar uma nova imagem, o worker prepara o conjunto de vistas novamente.</p>}
        <div className="form-grid">
          {batchMode ? <label>Arquivos do lote
            <input type="file" multiple accept="image/png,image/jpeg,image/webp" required={!batchFiles.length}
              onChange={(e) => setBatchFiles(Array.from(e.target.files ?? []))} />
            <small className="muted">{engine.views.length > 1
              ? `Use nome__vista no arquivo. Vistas exigidas: ${engine.views.join(", ")}.`
              : "Cada imagem gera um asset."} {batchFiles.length > 0 && `${batchFiles.length} arquivos selecionados.`}</small>
          </label> : engine.views.map((view) => <label key={`${engineId}-${view}`}>{views[view]}<input type="file" required={!files[view] && !existing?.[view]}
            accept="image/png,image/jpeg,image/webp" onChange={(e) => {
              const file = e.target.files?.[0];
              setFiles((old) => {
                const next = { ...old };
                if (file) next[view] = file;
                else delete next[view];
                return next;
              });
            }} />{files[view]?.name ?? (existing?.[view] ? "Reutilizar esta vista" : "")}</label>)}
          <label>Worker<select value={selectedWorker?.id ?? ""} onChange={(e) => setWorker(e.target.value)}>
            <option value="">Automático</option>
            {compatible.map((w) => <option key={w.id} value={w.id}>
              {w.name}{w.online && w.state === "enabled" ? "" : " (indisponível)"}
              {engineId !== "trellis2-gguf" && !w.capabilities.features?.includes("engine.reference-prep") ? " · PNG recortado" : ""}
            </option>)}
          </select></label>
        </div>
        {compatible.length === 0 && <p className="muted">O pedido ficará na fila até um worker compatível se registrar.</p>}
        <div className="st-foot">
          <button className="st-generate" disabled={create.isPending || !name.trim() || unavailable}><Sparkles size={18} /> {create.isPending ? "Enviando…" : "Enfileirar geração"}</button>
          {create.data && <Link to={create.data.route}>Acompanhar {create.data.label}</Link>}
        </div>
        {create.error && <ErrorNote error={create.error} />}
      </form>}
      {!assetId && <Link to="/legacy" className="st-hint">Estúdio clássico · TripoSR e Stable Fast 3D</Link>}
      <Link to="/workers" className="st-hint">Ver workers</Link>
  </div>;
}
