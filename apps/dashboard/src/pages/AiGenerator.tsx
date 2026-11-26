import { useMutation, useQuery } from "@tanstack/react-query";
import { Dices, Sparkles, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { Worker } from "../types";

const CATEGORIES = ["prop", "house", "apartment", "commercial", "skyscraper", "industrial", "hospital", "school", "university", "police", "fire_station", "transport_station", "warehouse", "government", "vehicle", "character", "tree"];
const PROFILES = ["prototype", "stylized_standard", "stylized_detailed", "high_quality"];

export function parseLods(text: string): number[] | null {
  const parts = text.split(/[,\s;]+/).filter(Boolean).map(Number);
  if (parts.some((n) => Number.isNaN(n) || n < 0.02 || n >= 1)) return null;
  return parts.every((n, i) => i === 0 || n < parts[i - 1]) ? parts : null;
}

export function AiGenerator() {
  const nav = useNavigate();
  const [source, setSource] = useState<"text" | "image">("text");
  const [name, setName] = useState("Edifício IA");
  const [prompt, setPrompt] = useState("");
  const [category, setCategory] = useState("house");
  const [size, setSize] = useState(8);
  const [seed, setSeed] = useState(1);
  const [profile, setProfile] = useState("stylized_standard");
  const [trellis, setTrellis] = useState(false);
  const [removeBg, setRemoveBg] = useState(true);
  const [lods, setLods] = useState("0.5, 0.25, 0.1");
  const [formats, setFormats] = useState<string[]>(["glb", "fbx"]);
  const [ref, setRef] = useState<{ id: string; width: number; height: number } | null>(null);
  const [upErr, setUpErr] = useState<string | null>(null);
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 8000 });
  const feature = source === "text" ? "ai.text_to_3d" : "ai.image_to_3d";
  const capable = (workers.data ?? []).filter((w) => w.online && w.state === "enabled" && w.capabilities.features?.includes(feature));
  const reasons = (workers.data ?? []).filter((w) => w.capabilities.ai?.enabled !== undefined && !w.capabilities.features?.includes(feature));
  const lodList = parseLods(lods);

  const upload = async (file: File) => {
    setUpErr(null);
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/v1/references", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      setUpErr(typeof j.detail === "string" ? j.detail : `falha no upload (${res.status})`);
      return;
    }
    setRef(await res.json());
  };

  const submit = useMutation({
    mutationFn: () =>
      api("/jobs", {
        method: "POST",
        json: {
          name,
          job_type: source === "text" ? "ai.text_to_3d" : "ai.image_to_3d",
          quality_profile: profile,
          formats,
          params: { category, seed, target_size_m: size, use_trellis2: trellis, remove_background: removeBg, lod_ratios: lodList ?? [], ...(source === "text" ? { prompt } : { reference_id: ref?.id }) },
        },
      }),
    onSuccess: () => nav("/queue"),
  });
  const ready = name && lodList && (source === "text" ? prompt.trim().length > 3 : !!ref);

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", gap: 14, alignItems: "start" }}>
      <div className="grid" style={{ gap: 14 }}>
        <div className="note">
          IA generativa <strong>complementa</strong> os geradores procedurais (que continuam sendo o caminho principal). Usa os workflows do Intel AI Playground via ComfyUI headless nos workers Intel. Cada node só oferece este modo depois de <strong>validado</strong> em hardware real.
        </div>
        <Panel title="Origem">
          <div className="row" role="tablist">
            <button role="tab" aria-selected={source === "text"} className={source === "text" ? "primary" : ""} onClick={() => setSource("text")}>
              Texto → imagem → 3D
            </button>
            <button role="tab" aria-selected={source === "image"} className={source === "image" ? "primary" : ""} onClick={() => setSource("image")}>
              Imagem de referência → 3D
            </button>
          </div>
          {source === "text" ? (
            <label className="field" style={{ marginTop: 12 }}>
              Descrição
              <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="ex.: hospital moderno de cinco andares com fachada de vidro e heliponto" aria-label="Descrição para a IA" />
              <span className="hint">O estilo “Premium Stylized Low/Mid Poly” é acrescentado automaticamente ao prompt.</span>
            </label>
          ) : (
            <div style={{ marginTop: 12 }}>
              <label className="btn">
                <Upload size={14} /> Enviar imagem (PNG/JPEG/WEBP, 64–4096 px)
                <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              </label>
              {ref && <span className="chip" style={{ marginLeft: 8 }}>{ref.id} · {ref.width}×{ref.height}</span>}
              {upErr && <div className="error-note">{upErr}</div>}
              <p className="muted" style={{ fontSize: 11 }}>Funciona melhor com um único objeto sobre fundo liso (recomendação do workflow da Intel).</p>
            </div>
          )}
        </Panel>
        <Panel title="Asset e qualidade">
          <div className="grid g4">
            <label className="field" style={{ gridColumn: "span 2" }}>
              Nome
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              Categoria (orçamento de triângulos)
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Seed
              <div className="row">
                <input type="number" min={0} value={seed} onChange={(e) => setSeed(Math.max(0, Number(e.target.value) || 0))} />
                <button className="icon" onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))} aria-label="Seed aleatória">
                  <Dices size={15} />
                </button>
              </div>
            </label>
            <label className="field">
              Altura real (m)
              <input type="number" min={0.2} step={0.5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
            <label className="field">
              Perfil de qualidade
              <select value={profile} onChange={(e) => setProfile(e.target.value)}>
                {PROFILES.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
            <label className="field">
              LODs (razões)
              <input value={lods} onChange={(e) => setLods(e.target.value)} aria-invalid={!lodList} />
              {!lodList && <span className="check-fail">decrescente, entre 0,02 e 1</span>}
            </label>
            <div className="field">
              Opções
              <label className="check">
                <input type="checkbox" checked={trellis} onChange={(e) => setTrellis(e.target.checked)} /> Usar TRELLIS.2 (alternativo)
              </label>
              <label className="check">
                <input type="checkbox" checked={removeBg} onChange={(e) => setRemoveBg(e.target.checked)} /> Remover fundo
              </label>
            </div>
          </div>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <span className="muted">Formatos:</span>
            <label className="check">
              <input type="checkbox" checked disabled /> GLB (+ LODs)
            </label>
            {["fbx", "blend"].map((f) => (
              <label key={f} className="check">
                <input type="checkbox" checked={formats.includes(f)} onChange={(e) => setFormats(e.target.checked ? [...formats, f] : formats.filter((x) => x !== f))} />
                {f.toUpperCase()}
              </label>
            ))}
          </div>
        </Panel>
      </div>
      <div className="grid" style={{ gap: 14, position: "sticky", top: 0 }}>
        <Panel title="Disponibilidade">
          {capable.length ? (
            <div className="check-ok">✔ {capable.length} worker(s) com IA validada: {capable.map((w) => w.name).join(", ")}</div>
          ) : (
            <div className="error-note">Nenhum worker oferece IA agora. O job ficaria na fila sem executar.</div>
          )}
          {!capable.length &&
            reasons.map((w) => (
              <div key={w.id} className="muted" style={{ fontSize: 12 }}>
                {w.name}: {w.capabilities.ai?.reason ?? "IA não configurada"}
              </div>
            ))}
          <ErrorNote error={submit.error} />
          <button className="primary" style={{ width: "100%", justifyContent: "center", marginTop: 12 }} disabled={!ready || submit.isPending} onClick={() => submit.mutate()}>
            <Sparkles size={15} /> Gerar com IA
          </button>
          <p className="muted" style={{ fontSize: 11 }}>
            Reserva VRAM no node (padrão 7000 MB). A compatibilidade com a Arc A750 só é afirmada após a validação em hardware.
          </p>
        </Panel>
      </div>
    </div>
  );
}
