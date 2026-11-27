import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { Job, Worker } from "../types";

interface Engine {
  id: string;
  label: string;
  resolutions: number[];
  views: string[];
  experimental: boolean;
  commercial_status: string;
}

const views: Record<string, string> = { front: "Frente", right: "Lateral direita", back: "Costas", three_quarter: "Vista 3/4" };

export function EngineLab() {
  const [query] = useSearchParams();
  const assetId = query.get("asset");
  const cache = useQueryClient();
  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api<{ items: Engine[] }>("/engines") });
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 15000 });
  const [engineId, setEngine] = useState("trellis2-gguf");
  const [name, setName] = useState(query.get("name") ?? "");
  const [category, setCategory] = useState("building");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [workerId, setWorker] = useState("");
  const [resolution, setResolution] = useState(1024);
  const [tokens, setTokens] = useState(49152);
  const [texture, setTexture] = useState(4096);
  const [seed, setSeed] = useState(1);
  const [structure, setStructure] = useState(7.5);
  const [shape, setShape] = useState(7.5);
  const [angle, setAngle] = useState(45);
  const [scale, setScale] = useState(1);
  const [skipDecimation, setSkipDecimation] = useState(false);
  const engine = engines.data?.items.find((item) => item.id === engineId);
  const compatible = (workers.data ?? []).filter((worker) =>
    worker.capabilities.features?.includes(`engine.${engineId}`));
  const selectedWorker = compatible.find((worker) => worker.id === workerId);
  const create = useMutation({
    mutationFn: async () => {
      if (!engine) throw new Error("Selecione um motor");
      const references = Object.fromEntries(await Promise.all(engine.views.map(async (view) => {
        const file = files[view];
        if (!file) throw new Error(`Envie a vista ${views[view]}`);
        const data = new FormData();
        data.append("file", file);
        const saved = await api<{ id: string }>("/references", { method: "POST", body: data });
        return [view, saved.id];
      })));
      return api<Job>("/jobs", { method: "POST", json: {
        name: name.trim(), asset_id: assetId ?? undefined, worker_id: selectedWorker?.id,
        job_type: "experimental.reconstruct",
        params: { engine: engineId, category, references, resolution, max_tokens: tokens,
          seed, texture_size: texture, structure_guidance: structure, shape_guidance: shape,
          mesh_scale: scale, three_quarter_angle: angle, skip_decimation: engineId !== "pixal3d-python" && skipDecimation },
      } });
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return <div className="engine-workbench">
    <Panel title={assetId ? "Gerar nova versão" : "Motores de reconstrução"}>
      <div className="form-grid">
        <label>Motor<select value={engineId} onChange={(e) => {
          setEngine(e.target.value);
          setResolution(1024);
          setTokens(e.target.value === "pixal3d-python" ? 131072 : 49152);
          setWorker("");
          create.reset();
        }}>
          {engines.data?.items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          <option value="procedural">Kit procedural</option>
        </select></label>
        {engineId === "procedural" ? <p>Crie uma construção através do <Link to="/generator">gerador procedural</Link>.</p> :
          <p className="muted">Experimental · revisão para uso comercial pendente</p>}
      </div>
      {engines.error && <ErrorNote error={engines.error} />}
      {engine && <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <div className="form-grid">
          <label>Nome<input value={name} required maxLength={120} onChange={(e) => setName(e.target.value)} /></label>
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
          <label>Orçamento de tokens<input type="number" min={1} value={tokens} required onChange={(e) => setTokens(Number(e.target.value))} /></label>
          <label>Seed<input type="number" min={0} value={seed} required onChange={(e) => setSeed(Number(e.target.value))} /></label>
          <label>Guidance da estrutura<input type="number" min={0} max={32} step={0.1} required value={structure} onChange={(e) => setStructure(Number(e.target.value))} /></label>
          <label>Guidance da forma<input type="number" min={0} max={32} step={0.1} required value={shape} onChange={(e) => setShape(Number(e.target.value))} /></label>
          {engineId !== "pixal3d-python" && <label className="check">
            <input type="checkbox" checked={skipDecimation} onChange={(e) => setSkipDecimation(e.target.checked)} />
            Pular a decimação do exportador GGUF
          </label>}
          {engine.views.length > 1 && <>
            <label>Azimute da vista 3/4 (°)<input type="number" min={1} max={359} step={0.1} required value={angle} onChange={(e) => setAngle(Number(e.target.value))} /></label>
            <label>Escala de projeção<input type="number" min={0.01} max={10} step={0.01} required value={scale} onChange={(e) => setScale(Number(e.target.value))} /></label>
          </>}
        </div>
        <h3>Referências</h3>
        {engine.id !== "trellis2-gguf" && <p className="muted">Use PNG com o objeto recortado e fundo transparente.</p>}
        <div className="form-grid">
          {engine.views.map((view) => <label key={view}>{views[view]}<input type="file" required={!files[view]}
            accept={engine.id !== "trellis2-gguf" ? "image/png" : "image/png,image/jpeg,image/webp"} onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) setFiles((old) => ({ ...old, [view]: file }));
            }} />{files[view]?.name}</label>)}
          <label>Worker<select value={selectedWorker?.id ?? ""} onChange={(e) => setWorker(e.target.value)}>
            <option value="">Automático</option>
            {compatible.map((w) => <option key={w.id} value={w.id}>{w.name}{w.online && w.state === "enabled" ? "" : " (indisponível)"}</option>)}
          </select></label>
        </div>
        {compatible.length === 0 && <p className="muted">O pedido ficará na fila até um worker compatível se registrar.</p>}
        <div className="row wrap">
          <button className="primary" disabled={create.isPending || !name.trim()}>{create.isPending ? "Enviando…" : "Enfileirar geração"}</button>
          {create.data && <Link to="/queue">Acompanhar {create.data.name}</Link>}
        </div>
        {create.error && <ErrorNote error={create.error} />}
      </form>}
    </Panel>
    <Panel title="Workers compatíveis">
      {compatible.length ? compatible.map((w) => <div key={w.id} className="engine-worker-line">
        <strong>{w.name}</strong><span className="muted">{w.online ? `${w.active_jobs} em execução` : "Offline"}</span>
        {w.online && w.telemetry.engine_gpu && <small className="muted">
          {w.telemetry.engine_gpu.temperature_c ?? "—"} °C · {w.telemetry.engine_gpu.utilization_percent ?? "—"}% GPU
          {w.telemetry.engine_gpu.vram_free_mb != null && ` · ${(w.telemetry.engine_gpu.vram_free_mb / 1024).toFixed(1)} GiB VRAM livre`}
        </small>}
      </div>) : <p className="muted">Nenhum worker anuncia este motor.</p>}
    </Panel>
  </div>;
}
