import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Dices, Save, Sparkles, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { GeneratorInfo, Preset, Worker } from "../types";

interface Form {
  name: string;
  category: string;
  style: string;
  seed: number;
  width: string;
  depth: string;
  floors: string;
  floor_height: string;
  roof: string;
  balconies: string;
  garage: string;
  wear: number;
  detail: number;
  texture_resolution: number;
  quality_profile: string;
  triangle_limit: string;
  formats: string[];
  priority: number;
  worker_id: string;
  variations: number;
  depends_on: string;
  scheduled_at: string;
  palette: string;
}

const DEFAULTS: Form = {
  name: "Casa residencial",
  category: "house",
  style: "classic",
  seed: 1,
  width: "",
  depth: "",
  floors: "",
  floor_height: "",
  roof: "",
  balconies: "",
  garage: "",
  wear: 0.15,
  detail: 1,
  texture_resolution: 512,
  quality_profile: "stylized_standard",
  triangle_limit: "",
  formats: ["glb"],
  priority: 0,
  worker_id: "",
  variations: 1,
  depends_on: "",
  scheduled_at: "",
  palette: "",
};

const num = (v: string) => (v.trim() === "" ? undefined : Number(v));
const tri = (v: string) => (v === "" ? undefined : v === "true");

export function buildParams(f: Form) {
  return {
    category: f.category,
    style: f.style,
    seed: f.seed,
    width: num(f.width),
    depth: num(f.depth),
    floors: num(f.floors),
    floor_height: num(f.floor_height),
    roof: f.roof || undefined,
    balconies: tri(f.balconies),
    garage: tri(f.garage),
    palette: f.palette || undefined,
    wear: f.wear,
    detail: f.detail,
    texture_resolution: f.texture_resolution,
  };
}

const CAT_LABEL: Record<string, string> = {
  house: "Casa",
  apartment: "Apartamentos",
  commercial: "Prédio comercial",
  skyscraper: "Arranha-céu",
  industrial: "Indústria",
  hospital: "Hospital",
  school: "Escola",
  university: "Universidade",
  police: "Delegacia",
  fire_station: "Quartel de bombeiros",
  transport_station: "Estação de transporte",
  warehouse: "Armazém",
  government: "Construção governamental",
};

export function Generator() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [f, setF] = useState<Form>(DEFAULTS);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((p) => ({ ...p, [k]: v }));
  const gen = useQuery({ queryKey: ["generators"], queryFn: () => api<GeneratorInfo[]>("/generators") });
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 10000 });
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api<Preset[]>("/presets") });
  const g = gen.data?.[0];
  const blenderOnline = (workers.data ?? []).some((w) => w.online && w.state === "enabled" && w.capabilities.features?.includes("blender"));
  const anyOnline = (workers.data ?? []).some((w) => w.online && w.state === "enabled");
  const budget = g?.budgets[f.category];
  const mult = g?.quality_profiles[f.quality_profile] ?? 1;
  const palettes = g?.palettes[f.style] ?? [];

  const submit = useMutation({
    mutationFn: async () => {
      const base = {
        name: f.name,
        params: buildParams(f),
        quality_profile: f.quality_profile,
        triangle_limit: num(f.triangle_limit),
        formats: f.formats,
        priority: f.priority,
        worker_id: f.worker_id || undefined,
        depends_on: f.depends_on.split(/[\s,]+/).filter(Boolean),
        scheduled_at: f.scheduled_at ? new Date(f.scheduled_at).toISOString() : undefined,
      };
      if (f.variations > 1) return api<{ id: string }>("/batches", { method: "POST", json: { name: f.name, count: f.variations, template: base, seed_start: f.seed } });
      return api<{ id: string }>("/jobs", { method: "POST", json: base });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["batches"] });
      nav("/queue");
    },
  });
  const savePreset = useMutation({
    mutationFn: (name: string) => api("/presets", { method: "POST", json: { name, data: f } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["presets"] }),
  });

  const [desc, setDesc] = useState("");
  const [planInfo, setPlanInfo] = useState<{ source: string; confidence: number; matched: string[]; notes: string[] } | null>(null);
  const plan = useMutation({
    mutationFn: () => api<{ params: Record<string, unknown>; name: string; source: string; confidence: number; matched: string[]; notes: string[] }>("/plan", { method: "POST", json: { description: desc } }),
    onSuccess: (r) => {
      const p = r.params as Partial<Record<string, string | number | boolean>>;
      setF((prev) => ({
        ...prev,
        name: r.name || prev.name,
        category: (p.category as string) ?? prev.category,
        style: (p.style as string) ?? prev.style,
        palette: "",
        seed: (p.seed as number) ?? prev.seed,
        width: p.width != null ? String(p.width) : "",
        depth: p.depth != null ? String(p.depth) : "",
        floors: p.floors != null ? String(p.floors) : "",
        roof: (p.roof as string) ?? "",
        balconies: p.balconies != null ? String(p.balconies) : "",
        garage: p.garage != null ? String(p.garage) : "",
        wear: (p.wear as number) ?? prev.wear,
        detail: (p.detail as number) ?? prev.detail,
      }));
      setPlanInfo(r);
    },
  });

  const expected = useMemo(() => (budget ? [Math.round(budget[0] * mult), Math.round(budget[1] * mult)] : null), [budget, mult]);

  return (
    <div>
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", gap: 14, alignItems: "start" }}>
      <div className="grid" style={{ gap: 14 }}>
        <Panel title="Descrição textual → parâmetros" actions={<span className="muted">regras PT/EN; LLM local opcional</span>}>
          <div className="row">
            <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="ex.: hospital moderno de cinco andares, 40 x 20 m, com heliponto" aria-label="Descrição textual" onKeyDown={(e) => e.key === "Enter" && desc.length > 2 && plan.mutate()} />
            <button disabled={desc.trim().length < 3 || plan.isPending} onClick={() => plan.mutate()}>
              <Wand2 size={14} /> Interpretar
            </button>
          </div>
          <ErrorNote error={plan.error} />
          {planInfo && (
            <div className="note" style={{ marginTop: 8 }}>
              Interpretado por <strong>{planInfo.source === "llm" ? "LLM local" : "regras"}</strong> (confiança {Math.round(planInfo.confidence * 100)}%): {planInfo.matched.join(" · ") || "nada reconhecido"}.
              {planInfo.notes.map((n) => (
                <div key={n}>⚠ {n}</div>
              ))}
              <div className="muted">Revise os campos abaixo antes de gerar; a descrição só preenche parâmetros do gerador procedural.</div>
            </div>
          )}
        </Panel>
        <Panel title="Asset">
          <div className="grid g3">
            <label className="field" style={{ gridColumn: "span 2" }}>
              Nome do asset
              <input value={f.name} onChange={(e) => set("name", e.target.value)} />
            </label>
            <label className="field">
              Seed
              <div className="row">
                <input type="number" min={0} value={f.seed} onChange={(e) => set("seed", Math.max(0, Number(e.target.value) || 0))} />
                <button className="icon" title="Seed aleatória" onClick={() => set("seed", Math.floor(Math.random() * 1_000_000))}>
                  <Dices size={15} />
                </button>
              </div>
            </label>
            <label className="field">
              Categoria
              <select value={f.category} onChange={(e) => set("category", e.target.value)}>
                {(g?.categories ?? [f.category]).map((c) => (
                  <option key={c} value={c}>
                    {CAT_LABEL[c] ?? c}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Estilo arquitetônico
              <select value={f.style} onChange={(e) => setF((p) => ({ ...p, style: e.target.value, palette: "" }))}>
                {Object.keys(g?.palettes ?? { [f.style]: [] }).map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Paleta
              <select value={f.palette} onChange={(e) => set("palette", e.target.value)}>
                <option value="">automática (pela seed)</option>
                {palettes.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
          </div>
        </Panel>
        <Panel title="Dimensões e arquitetura" actions={<span className="muted">vazio = automático por categoria + seed</span>}>
          <div className="grid g4">
            <label className="field">
              Comprimento (m)
              <input type="number" min={3} step={0.5} value={f.width} placeholder="auto" onChange={(e) => set("width", e.target.value)} />
            </label>
            <label className="field">
              Largura (m)
              <input type="number" min={3} step={0.5} value={f.depth} placeholder="auto" onChange={(e) => set("depth", e.target.value)} />
            </label>
            <label className="field">
              Andares
              <input type="number" min={1} max={80} value={f.floors} placeholder="auto" onChange={(e) => set("floors", e.target.value)} />
            </label>
            <label className="field">
              Pé-direito (m)
              <input type="number" min={2.2} step={0.1} value={f.floor_height} placeholder="auto" onChange={(e) => set("floor_height", e.target.value)} />
            </label>
            <label className="field">
              Telhado
              <select value={f.roof} onChange={(e) => set("roof", e.target.value)}>
                <option value="">automático</option>
                {["gable", "hip", "flat", "shed", "sawtooth"].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Varandas
              <select value={f.balconies} onChange={(e) => set("balconies", e.target.value)}>
                <option value="">automático</option>
                <option value="true">sim</option>
                <option value="false">não</option>
              </select>
            </label>
            <label className="field">
              Garagem
              <select value={f.garage} onChange={(e) => set("garage", e.target.value)}>
                <option value="">automático</option>
                <option value="true">sim</option>
                <option value="false">não</option>
              </select>
            </label>
            <label className="field">
              Conservação: {Math.round((1 - f.wear) * 100)}%
              <input type="range" min={0} max={1} step={0.05} value={f.wear} onChange={(e) => set("wear", Number(e.target.value))} />
              <span className="hint">100% = novo · 0% = desgastado</span>
            </label>
          </div>
        </Panel>
        <Panel title="Qualidade e exportação">
          <div className="grid g4">
            <label className="field">
              Perfil de qualidade
              <select value={f.quality_profile} onChange={(e) => set("quality_profile", e.target.value)}>
                {Object.keys(g?.quality_profiles ?? { stylized_standard: 1 }).map((q) => (
                  <option key={q}>{q}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Limite de triângulos
              <input type="number" min={50} value={f.triangle_limit} placeholder={expected ? `${expected[1]} (perfil)` : "perfil"} onChange={(e) => set("triangle_limit", e.target.value)} />
            </label>
            <label className="field">
              Resolução das texturas
              <select value={f.texture_resolution} onChange={(e) => set("texture_resolution", Number(e.target.value))}>
                {[128, 256, 512, 1024, 2048].map((r) => (
                  <option key={r} value={r}>
                    {r}px
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Detalhe geométrico
              <select value={f.detail} onChange={(e) => set("detail", Number(e.target.value))}>
                <option value={0}>0 – simplificado</option>
                <option value={1}>1 – padrão</option>
                <option value={2}>2 – molduras e venezianas</option>
              </select>
            </label>
          </div>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <span className="muted">Formatos:</span>
            <label className="check">
              <input type="checkbox" checked disabled /> GLB (sempre)
            </label>
            {(["blend", "fbx"] as const).map((fmt) => (
              <label key={fmt} className="check" title={blenderOnline ? "" : "Requer um worker com Blender online"}>
                <input
                  type="checkbox"
                  checked={f.formats.includes(fmt)}
                  disabled={!blenderOnline}
                  onChange={(e) => set("formats", e.target.checked ? [...f.formats, fmt] : f.formats.filter((x) => x !== fmt))}
                />
                {fmt.toUpperCase()}
              </label>
            ))}
            {!blenderOnline && <span className="muted">(BLEND/FBX exigem worker com Blender)</span>}
          </div>
        </Panel>
        <Panel title="Fila">
          <div className="grid g4">
            <label className="field">
              Prioridade ({f.priority})
              <input type="range" min={-10} max={10} value={f.priority} onChange={(e) => set("priority", Number(e.target.value))} />
            </label>
            <label className="field">
              Worker
              <select value={f.worker_id} onChange={(e) => set("worker_id", e.target.value)}>
                <option value="">seleção automática</option>
                {(workers.data ?? []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} ({w.kind}){w.online ? "" : " — offline"}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Agendar para
              <input type="datetime-local" value={f.scheduled_at} onChange={(e) => set("scheduled_at", e.target.value)} />
            </label>
            <label className="field">
              Depende dos jobs (ids)
              <input value={f.depends_on} placeholder="job_abc, job_def" onChange={(e) => set("depends_on", e.target.value)} />
            </label>
          </div>
        </Panel>
        <Panel title="Planejado (ainda não disponível)">
          <div className="grid g3 soon">
            {["Prompt negativo", "Imagem de referência", "Modelo de IA", "Colisões avançadas", "Níveis de detalhe (LOD)", "Animações"].map((x) => (
              <label key={x} className="field">
                <span>
                  {x}
                  <span className="tag">M2–M4</span>
                </span>
                <input disabled placeholder="Requer providers de IA locais (Milestone 2+)" />
              </label>
            ))}
          </div>
        </Panel>
      </div>
      <div className="grid" style={{ gap: 14, position: "sticky", top: 0 }}>
        <Panel title="Resumo">
          <dl className="kv">
            <dt>Gerador</dt>
            <dd className="mono">{g ? `${g.id}@${g.version}` : "—"}</dd>
            <dt>Orçamento LOD0</dt>
            <dd>{expected ? `${expected[0]}–${expected[1]} tris` : "—"}</dd>
            <dt>Variações</dt>
            <dd>
              <input type="number" min={1} max={1000} value={f.variations} onChange={(e) => set("variations", Math.max(1, Math.min(1000, Number(e.target.value) || 1)))} />
            </dd>
            <dt>Seeds</dt>
            <dd className="mono">{f.variations > 1 ? `${f.seed} … ${f.seed + f.variations - 1}` : f.seed}</dd>
            <dt>Workers online</dt>
            <dd>{anyOnline ? "sim" : <span className="check-warn">nenhum — o job ficará na fila</span>}</dd>
          </dl>
          <ErrorNote error={submit.error} />
          <div className="row sticky-actions" style={{ marginTop: 12 }}>
            <button className="primary" style={{ flex: 1, justifyContent: "center" }} disabled={!f.name || submit.isPending} onClick={() => submit.mutate()}>
              <Sparkles size={15} /> {f.variations > 1 ? `Gerar ${f.variations} variações` : "Gerar asset"}
            </button>
          </div>
        </Panel>
        <Panel title="Presets">
          <div className="row">
            <select
              defaultValue=""
              onChange={(e) => {
                const p = presets.data?.find((x) => x.id === e.target.value);
                if (p) setF({ ...DEFAULTS, ...(p.data as Partial<Form>) });
              }}
            >
              <option value="">carregar preset…</option>
              {(presets.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              className="icon"
              title="Salvar configuração atual como preset"
              onClick={() => {
                const n = window.prompt("Nome do preset");
                if (n) savePreset.mutate(n);
              }}
            >
              <Save size={15} />
            </button>
          </div>
        </Panel>
      </div>
    </div>
    </div>
  );
}
