import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Sparkles, X } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { Worker } from "../types";

export const MAX_IMAGE_MB = 10;

/** Presets for a low/mid-poly game. `tris` is the LOD0 triangle target; the rest follows from it. */
export const PRESETS = {
  low: { label: "Low poly", hint: "personagens secundários, props, mobile", tris: 1500, profile: "prototype", tex: 512, lods: [0.5, 0.25] },
  mid: { label: "Mid poly", hint: "equilíbrio para a maioria dos assets", tris: 6000, profile: "stylized_standard", tex: 1024, lods: [0.5, 0.25, 0.1] },
  high: { label: "Mid-alto", hint: "heróis e objetos em destaque", tris: 15000, profile: "stylized_detailed", tex: 2048, lods: [0.5, 0.25, 0.1] },
  custom: { label: "Personalizado", hint: "você define o número de triângulos", tris: 3000, profile: "stylized_standard", tex: 1024, lods: [0.5, 0.25] },
} as const;
type PresetKey = keyof typeof PRESETS;

const PROVIDERS = {
  triposr: { title: "TripoSR", note: "MIT — uso comercial livre" },
  sf3d: { title: "Stable Fast 3D", note: "licença Stability: uso comercial exige registro" },
} as const;

export function parseLods(text: string): number[] | null {
  const parts = text.split(/[,\s;]+/).filter(Boolean).map(Number);
  if (parts.some((n) => Number.isNaN(n) || n < 0.02 || n >= 1)) return null;
  return parts.every((n, i) => i === 0 || n < parts[i - 1]) ? parts : null;
}

/** Returns an error message when the file is not acceptable (checked before sending; the server checks again). */
export function checkImageFile(f: { type: string; size: number }): string | null {
  if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) return "use PNG, JPEG ou WEBP";
  if (f.size > MAX_IMAGE_MB * 1024 * 1024) return `maior que ${MAX_IMAGE_MB} MB`;
  return null;
}

interface Item {
  key: string;
  file: File;
  url: string;
  error: string | null;
}

export function AiGenerator() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const [preset, setPreset] = useState<PresetKey>("mid");
  const [tris, setTris] = useState<number>(PRESETS.mid.tris);
  const [size, setSize] = useState(2);
  const [provider, setProvider] = useState<"triposr" | "sf3d">("triposr");
  const [advanced, setAdvanced] = useState(false);
  const [tex, setTex] = useState<number>(PRESETS.mid.tex);
  const [lods, setLods] = useState<string>(PRESETS.mid.lods.join(", "));
  const [category, setCategory] = useState("prop");
  const [formats, setFormats] = useState<string[]>(["glb", "fbx", "blend"]);
  const [progress, setProgress] = useState<string | null>(null);

  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 8000 });
  const online = (workers.data ?? []).filter((w) => w.online && w.state === "enabled");
  const has = (p: string) => online.some((w) => w.capabilities.features?.includes(`provider.${p}`));
  const reasons = (workers.data ?? []).map((w) => w.capabilities.cpu3d?.providers?.[provider]?.reason).filter(Boolean);
  const lodList = parseLods(lods);

  const pick = (k: PresetKey) => {
    setPreset(k);
    const p = PRESETS[k];
    setTris(p.tris);
    setTex(p.tex);
    setLods(p.lods.join(", "));
  };
  const add = (files: FileList | File[]) => {
    const next: Item[] = [];
    for (const f of Array.from(files)) {
      next.push({ key: `${f.name}-${f.size}-${f.lastModified}-${Math.random()}`, file: f, url: URL.createObjectURL(f), error: checkImageFile(f) });
    }
    setItems((cur) => [...cur, ...next]);
  };
  const remove = (key: string) => setItems((cur) => cur.filter((i) => i.key !== key));
  const valid = items.filter((i) => !i.error);

  const upload = async (file: File): Promise<string> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/v1/references", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : `falha no upload (${res.status})`);
    return j.id as string;
  };

  const submit = useMutation({
    mutationFn: async () => {
      const preset_ = PRESETS[preset];
      for (const [n, it] of valid.entries()) {
        setProgress(`Enviando ${n + 1}/${valid.length}: ${it.file.name}`);
        const id = await upload(it.file);
        await api("/jobs", {
          method: "POST",
          json: {
            name: it.file.name.replace(/\.[^.]+$/, "").slice(0, 80) || "Asset",
            job_type: "ai.image_to_3d",
            quality_profile: preset_.profile,
            formats,
            params: { provider, reference_id: id, category, target_size_m: size, lod_ratios: lodList ?? [], texture_resolution: tex, max_triangles: tris },
          },
        });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      nav("/queue");
    },
    onSettled: () => setProgress(null),
  });
  const ready = valid.length > 0 && tris >= 200 && tris <= 200000 && !!lodList && size > 0;

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 320px", gap: 14, alignItems: "start" }}>
      <div className="grid" style={{ gap: 14 }}>
        <Panel title="1 · Imagens de referência">
          <div
            className="card"
            role="button"
            tabIndex={0}
            aria-label="Escolher imagens"
            onClick={() => input.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              add(e.dataTransfer.files);
            }}
            style={{ padding: 28, textAlign: "center", cursor: "pointer", borderStyle: "dashed", outline: over ? "2px solid var(--accent)" : undefined }}
          >
            <ImagePlus size={28} />
            <div style={{ marginTop: 6 }}>
              <strong>Arraste as imagens aqui</strong> ou clique para escolher
            </div>
            <div className="muted" style={{ fontSize: 12 }}>PNG, JPEG ou WEBP · até {MAX_IMAGE_MB} MB cada · um objeto por imagem, fundo liso. Cada imagem vira um modelo.</div>
            <input
              ref={input}
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files) add(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          {items.length > 0 && (
            <div className="row wrap" style={{ marginTop: 12, gap: 10 }}>
              {items.map((i) => (
                <div key={i.key} style={{ position: "relative", width: 110 }}>
                  <img src={i.url} alt={i.file.name} style={{ width: 110, height: 110, objectFit: "contain", background: "var(--panel-2)", borderRadius: 6, opacity: i.error ? 0.4 : 1 }} />
                  <button className="icon ghost" aria-label={`Remover ${i.file.name}`} style={{ position: "absolute", top: 2, right: 2 }} onClick={() => remove(i.key)}>
                    <X size={14} />
                  </button>
                  <div className="muted" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={i.file.name}>{i.file.name}</div>
                  {i.error && <div className="check-fail" style={{ fontSize: 11 }}>{i.error}</div>}
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="2 · Quantos polígonos?">
          <div className="grid g4">
            {(Object.keys(PRESETS) as PresetKey[]).map((k) => (
              <label key={k} className="card" style={{ padding: 10, cursor: "pointer", outline: preset === k ? "2px solid var(--accent)" : undefined }}>
                <div className="row">
                  <input type="radio" name="preset" checked={preset === k} onChange={() => pick(k)} />
                  <strong>{PRESETS[k].label}</strong>
                </div>
                <div style={{ fontSize: 13, marginTop: 4 }}>{k === "custom" ? "você escolhe" : `~${PRESETS[k].tris.toLocaleString("pt-BR")} triângulos`}</div>
                <div className="muted" style={{ fontSize: 11 }}>{PRESETS[k].hint}</div>
              </label>
            ))}
          </div>
          <div className="grid g4" style={{ marginTop: 12 }}>
            <label className="field">
              Triângulos do modelo final (LOD0)
              <input type="number" min={200} max={200000} step={100} value={tris} onChange={(e) => { setTris(Number(e.target.value)); setPreset("custom"); }} />
            </label>
            <label className="field">
              Altura real (m)
              <input type="number" min={0.1} step={0.5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
          </div>
          <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
            O polimento é automático: o Blender solda a malha, reduz até o número acima, refaz o UV e transfere cor e relevo do modelo detalhado para a textura. Também gera os LODs.
          </p>
        </Panel>

        <Panel title="Opções avançadas" actions={<button onClick={() => setAdvanced(!advanced)}>{advanced ? "Esconder" : "Mostrar"}</button>}>
          {advanced ? (
            <div className="grid g4">
              <label className="field">
                Modelo de IA
                <select value={provider} onChange={(e) => setProvider(e.target.value as "triposr" | "sf3d")}>
                  {Object.entries(PROVIDERS).map(([k, p]) => (
                    <option key={k} value={k}>{p.title} — {p.note}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Textura
                <select value={tex} onChange={(e) => setTex(Number(e.target.value))}>
                  {[256, 512, 1024, 2048].map((r) => (
                    <option key={r} value={r}>{r} px</option>
                  ))}
                </select>
              </label>
              <label className="field">
                LODs (razões)
                <input value={lods} onChange={(e) => setLods(e.target.value)} aria-invalid={!lodList} />
                {!lodList && <span className="check-fail">decrescente, entre 0,02 e 1</span>}
              </label>
              <label className="field">
                Categoria
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  {["prop", "house", "commercial", "industrial", "vehicle", "character", "tree"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              <div className="row wrap" style={{ gridColumn: "1 / -1" }}>
                <span className="muted">Formatos:</span>
                <label className="check"><input type="checkbox" checked disabled /> GLB</label>
                {["fbx", "blend"].map((f) => (
                  <label key={f} className="check">
                    <input type="checkbox" checked={formats.includes(f)} onChange={(e) => setFormats(e.target.checked ? [...formats, f] : formats.filter((x) => x !== f))} />
                    {f.toUpperCase()}
                  </label>
                ))}
              </div>
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 12 }}>
              Padrão: {PROVIDERS[provider].title} · textura {tex}px · LODs {lods} · GLB + FBX + BLEND.
            </div>
          )}
        </Panel>
      </div>

      <div style={{ position: "sticky", top: 0 }}>
        <Panel title="Gerar">
          <div style={{ fontSize: 13 }}>
            {valid.length} imagem(ns) · {PRESETS[preset].label} · ~{tris.toLocaleString("pt-BR")} triângulos
          </div>
          {has(provider) ? (
            <div className="check-ok" style={{ marginTop: 8 }}>✔ {PROVIDERS[provider].title} disponível</div>
          ) : (
            <div className="error-note" style={{ marginTop: 8 }}>
              {PROVIDERS[provider].title} não está disponível agora; o job ficaria na fila.
              {reasons.map((r, i) => <div key={i} className="muted" style={{ fontSize: 12 }}>{r}</div>)}
            </div>
          )}
          {progress && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{progress}</div>}
          <ErrorNote error={submit.error} />
          <button className="primary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} disabled={!ready || submit.isPending} onClick={() => submit.mutate()}>
            <Sparkles size={15} /> Gerar {valid.length > 1 ? `${valid.length} modelos 3D` : "modelo 3D"}
          </button>
        </Panel>
      </div>
    </div>
  );
}
