import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, ChevronDown, ImagePlus, Images, PenLine, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote } from "../components/ui";
import { geometryProfiles, type GeometryProfile } from "../geometryProfiles";
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
  prompt?: string;
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

type InputMode = "image" | "multi" | "text";
const inputModes = [
  { id: "image", label: "Imagem", Icon: ImagePlus },
  { id: "multi", label: "Múltiplas vistas", Icon: Images },
  { id: "text", label: "Descrição", Icon: PenLine },
] as const;

function ImageSlot({ label, file, archived, broad, onChange }: {
  label: string; file?: File; archived?: string; broad?: boolean; onChange: (file: File | undefined) => void;
}) {
  const [preview, setPreview] = useState<{ file: File; url: string }>();
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return <div className={`af-input-item${broad ? " af-input-slot-wide" : ""}`}>
    <label className={`af-input-slot${broad ? " af-input-slot-wide" : ""}`}>
    <input type="file" aria-label={label} accept="image/png,image/jpeg,image/webp"
      onChange={(event) => {
        const selected = event.currentTarget.files?.[0];
        if (selected) onChange(selected);
        event.currentTarget.value = "";
      }} />
    {preview?.file === file && preview?.url ? <img src={preview.url} alt="" /> : <ImagePlus size={broad ? 24 : 17} />}
    <strong>{label}</strong>
    <small title={file?.name}>{file?.name ?? (archived ? "Reutilizar esta vista" : broad ? "Selecione ou solte a imagem" : "Adicionar vista")}</small>
    </label>
    {file && <button type="button" className="af-remove-image icon" aria-label={`Remover imagem: ${label}`} onClick={() => onChange(undefined)}>
      <X size={15} />
    </button>}
  </div>;
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

function ReconstructionForm({ source, onCreated }: { source?: Asset; onCreated: (jobId: string, profile: GeometryProfile) => void }) {
  const assetId = source?.id;
  const recipe = source?.manifest?.generation_params as Recipe | undefined;
  const cache = useQueryClient();
  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api<{ items: Engine[] }>("/engines") });
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 15000 });
  const [engineId, setEngine] = useState(recipe?.engine ?? "trellis2-gguf");
  const [mode, setMode] = useState<InputMode>(recipe?.prompt ? "text"
    : recipe?.engine === "pixal3d-mv" || recipe?.engine === "pixal3d-python" ? "multi" : "image");
  const [prompt, setPrompt] = useState(recipe?.prompt ?? "");
  const [profile, setProfile] = useState<GeometryProfile>("master");
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
  const textMode = mode === "text";
  const modeEngines = (engines.data?.items ?? []).filter((item) => (item.views.length > 1) === (mode === "multi"));
  const engine = modeEngines.find((item) => item.id === engineId);
  const compatible = (workers.data ?? []).filter((worker) =>
    worker.capabilities.features?.includes(`engine.${engineId}`) &&
    (!textMode || worker.capabilities.features.includes("engine.text-reference")));
  const historicalWorker = compatible.find((w) => {
    const name = w.name.toLowerCase();
    return recipe?.archive?.worker === "spark" ? name.includes("spark") : recipe?.archive?.worker === "4090" && name.includes("4090");
  });
  const selectedWorker = compatible.find((worker) => worker.id === (workerId ?? historicalWorker?.id));
  const unavailable = !!selectedWorker && (!selectedWorker.online || selectedWorker.state !== "enabled");
  const textAvailable = compatible.some((worker) => worker.online && worker.state === "enabled");
  const hasImages = batchMode ? batchFiles.length > 0 : !!engine?.views.every((view) => files[view] || existing?.[view]);
  const options = { engine: engineId, category, resolution, max_tokens: tokens, seed, texture_size: texture,
    structure_guidance: structure, shape_guidance: shape, mesh_scale: scale, three_quarter_angle: angle,
    skip_decimation: skipDecimation };
  const create = useMutation({
    mutationFn: async () => {
      if (!engine || unavailable) throw new Error("Selecione um motor e um worker disponível.");
      if (textMode) {
        if (!textAvailable || !prompt.trim()) throw new Error("Informe a descrição e confirme que há um worker disponível.");
        const job = await api<Job>("/jobs", { method: "POST", json: {
          name: name.trim() || prompt.trim().slice(0, 100), asset_id: assetId, worker_id: selectedWorker?.id,
          job_type: "experimental.reconstruct", params: { ...options, references: {}, prompt: prompt.trim() },
        } });
        return { jobId: job.id, label: job.name, route: "/queue" };
      }
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
        params: { ...options, references: refs[index],
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
      if (result.jobId) onCreated(result.jobId, profile);
      cache.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  function switchMode(next: InputMode) {
    if (next === "text" && files.front && name === files.front.name.replace(/\.[^.]+$/, "").slice(0, 120)) setName("");
    setMode(next);
    setWorker("");
    create.reset();
    if ((next === "multi") !== (mode === "multi")) {
      setEngine(next === "multi" ? "pixal3d-mv" : "trellis2-gguf");
      setResolution(1024);
    }
  }

  function chooseEngine(id: string) {
    const next = modeEngines.find((item) => item.id === id);
    if (!next) return;
    setEngine(id);
    if (!next.resolutions.includes(resolution)) setResolution(next.resolutions[0]);
    if (!recipe && tokens === 49152 && id === "pixal3d-python") setTokens(131072);
    setWorker("");
    create.reset();
  }

  return <form className="af-workflow" onSubmit={(event) => { event.preventDefault(); create.mutate(); }} onInvalidCapture={(event) => {
    (event.target as HTMLElement).closest("details")?.setAttribute("open", "");
  }}>
    <div className="af-workflow-body">
      <header className="af-workflow-title">
        <Sparkles size={18} />
        <h2>{assetId ? "Repetir geração" : "Criar modelo"}</h2>
      </header>
      <div className="af-input-modes" role="group" aria-label="Entrada do modelo">
        {inputModes.map(({ id, label, Icon }) => <button key={id} type="button" aria-pressed={mode === id} onClick={() => switchMode(id)}>
          <Icon size={16} />{label}
        </button>)}
      </div>

      {recipe?.archive && <p className="af-field-hint">
        Experimento na {recipe.archive.worker === "4090" ? "RTX 4090" : "DGX Spark"}. Resolução efetiva {recipe.archive.effective_resolution ?? "não registrada"}.
        {recipe.archive.replay_issue && ` ${recipe.archive.replay_issue}`}
        {unavailable && " Selecione um worker disponível nos ajustes avançados."}
      </p>}
      {engines.error && <ErrorNote error={engines.error} />}
      {textMode ? <div className="af-prompt">
        <label htmlFor="model-description">Descreva o que quer criar</label>
        <textarea id="model-description" required maxLength={1600} rows={5} value={prompt}
          placeholder="Uma máquina de venda retrô de metal azul, com cantos arredondados e botões laranja…"
          onChange={(event) => setPrompt(event.target.value)} />
        <p className="af-field-hint">A Z-Image cria a referência que o motor reconstrói em 3D.</p>
      </div> : <>
        {!assetId && <label className="af-batch-toggle"><input type="checkbox" checked={batchMode} onChange={(event) => setBatchMode(event.target.checked)} /> Enviar em lote</label>}
        {batchMode ? <>
          <label className="af-input-slot af-input-slot-wide">
          <input type="file" aria-label="Referências do lote" multiple accept="image/png,image/jpeg,image/webp"
            onChange={(event) => {
              const selected = Array.from(event.currentTarget.files ?? []);
              if (selected.length) setBatchFiles(selected);
              event.currentTarget.value = "";
            }} />
          <Images size={24} />
          <strong>{batchFiles.length === 1 ? "1 imagem selecionada" : batchFiles.length ? `${batchFiles.length} imagens selecionadas` : "Selecionar imagens do lote"}</strong>
          <small>{mode === "multi" ? "Use nome__front, __right, __back e __three_quarter" : "Cada imagem cria um modelo"}</small>
          </label>
          {batchFiles.length > 0 && <div className="af-batch-files">
            <button type="button" onClick={() => setBatchFiles([])}>Limpar lote</button>
            <ul aria-label="Imagens do lote">
              {batchFiles.map((file, index) => <li key={`${file.name}:${index}`}>
                <span title={file.name}>{file.name}</span>
                <button type="button" className="icon" aria-label={`Remover ${file.name}`}
                  onClick={() => setBatchFiles((current) => current.filter((_, position) => position !== index))}><X size={15} /></button>
              </li>)}
            </ul>
          </div>}
        </> : <div className="af-input-grid">
          {engine?.views.map((view) => <ImageSlot key={`${mode}:${view}`} label={views[view]} broad={view === "front"}
            file={files[view]} archived={existing?.[view]} onChange={(file) => {
              setFiles((old) => {
                const next = { ...old };
                if (file) next[view] = file;
                else delete next[view];
                return next;
              });
              if (file && view === "front") setName((old) => old || file.name.replace(/\.[^.]+$/, "").slice(0, 120));
            }} />)}
        </div>}
        <p className="af-field-hint">{usePrepared
          ? "Vistas arquivadas prontas para repetir. Substituir uma imagem refaz a preparação."
          : "PNG, JPEG ou WebP."}</p>
      </>}

      <div className="af-basics">
        <label>{!textMode && batchMode ? "Nome do lote" : "Nome"}
          <input value={name} required={!textMode} maxLength={120} placeholder={textMode ? "Opcional" : "Nome do asset"} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>Categoria<select value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="building">Construção</option><option value="vehicle">Veículo</option>
          <option value="npc">Personagem</option><option value="prop">Objeto</option>
        </select></label>
      </div>

      <details className="af-settings">
        <summary><SlidersHorizontal size={16} /><span>Geometria e textura</span><ChevronDown size={14} /></summary>
        <div className="af-settings-fields">
          <label className="af-field-wide">Motor<select aria-label="Motor" value={engineId} onChange={(event) => chooseEngine(event.target.value)}>
            {modeEngines.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select></label>
          <label>Resolução<select value={resolution} onChange={(event) => setResolution(Number(event.target.value))}>
            {engine?.resolutions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select></label>
          <label>Textura (px)<select value={texture} onChange={(event) => setTexture(Number(event.target.value))}>
            {[512, 1024, 2048, 4096, 8192, 16384].map((value) => <option key={value} value={value}>{value}</option>)}
          </select></label>
          <label className="af-field-wide">Perfil geométrico<select value={profile} onChange={(event) => setProfile(event.target.value as GeometryProfile)}>
            {Object.entries(geometryProfiles).map(([id, preset]) => <option key={id} value={id}>{preset.label}</option>)}
          </select></label>
          <p className="af-field-hint af-field-wide">O perfil fica selecionado em Preparar geometria após gerar o master.</p>
        </div>
      </details>

      <details className="af-settings" open={source ? true : undefined}>
        <summary><span>Ajustes avançados</span><ChevronDown size={14} /></summary>
        <div className="af-settings-fields">
          <label>Orçamento de tokens<input type="number" min={1} value={tokens} required onChange={(event) => setTokens(Number(event.target.value))} /></label>
          <label>Seed<input type="number" min={0} value={seed} required onChange={(event) => setSeed(Number(event.target.value))} /></label>
          <label>Guidance da estrutura<input type="number" min={0} max={32} step={0.1} placeholder="Padrão do motor"
            value={structure ?? ""} onChange={(event) => setStructure(event.target.value === "" ? null : Number(event.target.value))} /></label>
          <label>Guidance da forma<input type="number" min={0} max={32} step={0.1} placeholder="Padrão do motor"
            value={shape ?? ""} onChange={(event) => setShape(event.target.value === "" ? null : Number(event.target.value))} /></label>
          <label className="af-batch-toggle af-field-wide"><input type="checkbox" checked={!skipDecimation} onChange={(event) => setSkipDecimation(!event.target.checked)} />
            Aplicar decimação na exportação
          </label>
          {mode === "multi" && <>
            <label>Azimute 3/4 (°)<input type="number" min={1} max={359} step={0.1} required value={angle} onChange={(event) => setAngle(Number(event.target.value))} /></label>
            <label>Escala de projeção<input type="number" min={0.01} max={10} step={0.01} required value={scale} onChange={(event) => setScale(Number(event.target.value))} /></label>
          </>}
          <label className="af-field-wide">Worker<select value={selectedWorker?.id ?? ""} onChange={(event) => setWorker(event.target.value)}>
            <option value="">Automático</option>
            {compatible.map((worker) => <option key={worker.id} value={worker.id}>{worker.name}{worker.online && worker.state === "enabled" ? "" : " (indisponível)"}</option>)}
          </select></label>
        </div>
      </details>
      {!source && <Link className="af-legacy" to="/legacy">Estúdio clássico <ArrowUpRight size={13} /></Link>}
    </div>

    <div className="af-workflow-footer">
      <div className="af-engine-summary" title="Motor experimental com revisão comercial pendente">
        <span>{engine?.label ?? "Carregando motores…"}</span><span>{geometryProfiles[profile].label}</span>
      </div>
      {textMode && !textAvailable && !workers.isLoading && <p className="af-field-hint">A geração por descrição aguarda um worker com Z-Image.</p>}
      <ErrorNote error={create.error} />
      <button className="st-generate" disabled={create.isPending || unavailable || !engine || (textMode ? !prompt.trim() || !textAvailable : !name.trim() || !hasImages)}>
        <Sparkles size={18} /> {create.isPending ? "Enviando…" : "Enfileirar geração"}
      </button>
      {create.data && <Link to={create.data.route}>Acompanhar {create.data.label}</Link>}
    </div>
  </form>;
}
