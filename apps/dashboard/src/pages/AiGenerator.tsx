import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, Upload } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { Worker } from "../types";

const CATEGORIES = ["prop", "house", "apartment", "commercial", "skyscraper", "industrial", "hospital", "school", "university", "police", "fire_station", "transport_station", "warehouse", "government", "vehicle", "character", "tree"];
const PROFILES = ["prototype", "stylized_standard", "stylized_detailed", "high_quality"];

const PROVIDERS: Record<string, { title: string; blurb: string; license: string }> = {
  sf3d: {
    title: "Stable Fast 3D (CPU)",
    blurb: "Textura PBR (albedo/rugosidade/metal/normal) com UV; melhor candidato para materiais.",
    license: "Licença Stability AI Community: uso comercial exige registro na Stability e receita < US$ 1 mi/ano; exige “Powered by Stability AI”.",
  },
  triposr: {
    title: "TripoSR (CPU)",
    blurb: "Alternativa: textura baked (ou cor por vértice se o bake falhar).",
    license: "MIT (código e pesos): sem restrições comerciais.",
  },
};

export function parseLods(text: string): number[] | null {
  const parts = text.split(/[,\s;]+/).filter(Boolean).map(Number);
  if (parts.some((n) => Number.isNaN(n) || n < 0.02 || n >= 1)) return null;
  return parts.every((n, i) => i === 0 || n < parts[i - 1]) ? parts : null;
}

export function AiGenerator() {
  const nav = useNavigate();
  const [provider, setProvider] = useState<"sf3d" | "triposr">("sf3d");
  const [name, setName] = useState("Asset a partir de imagem");
  const [category, setCategory] = useState("house");
  const [size, setSize] = useState(8);
  const [profile, setProfile] = useState("stylized_standard");
  const [tex, setTex] = useState("");
  const [mc, setMc] = useState("");
  const [remesh, setRemesh] = useState("none");
  const [maxTris, setMaxTris] = useState("");
  const [lods, setLods] = useState("0.5, 0.25, 0.1");
  const [formats, setFormats] = useState<string[]>(["glb", "fbx", "blend"]);
  const [ref, setRef] = useState<{ id: string; width: number; height: number } | null>(null);
  const [refUrl, setRefUrl] = useState<string | null>(null);
  const [upErr, setUpErr] = useState<string | null>(null);
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 8000 });
  const online = (workers.data ?? []).filter((w) => w.online && w.state === "enabled");
  const capable = online.filter((w) => w.capabilities.features?.includes(`provider.${provider}`));
  const status = (workers.data ?? []).map((w) => w.capabilities.cpu3d?.providers?.[provider]).filter(Boolean);
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
    setRefUrl(URL.createObjectURL(file));
  };

  const submit = useMutation({
    mutationFn: () =>
      api("/jobs", {
        method: "POST",
        json: {
          name,
          job_type: "ai.image_to_3d",
          quality_profile: profile,
          formats,
          params: {
            provider,
            reference_id: ref?.id,
            category,
            target_size_m: size,
            lod_ratios: lodList ?? [],
            ...(tex ? { texture_resolution: Number(tex) } : {}),
            ...(provider === "triposr" && mc ? { mc_resolution: Number(mc) } : {}),
            ...(provider === "sf3d" ? { remesh } : {}),
            ...(maxTris ? { max_triangles: Number(maxTris) } : {}),
          },
        },
      }),
    onSuccess: () => nav("/queue"),
  });
  const ready = name && lodList && ref;

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 340px", gap: 14, alignItems: "start" }}>
      <div className="grid" style={{ gap: 14 }}>
        <div className="note">
          Geração <strong>complementar</strong> ao procedural: imagem de referência → modelo 3D texturizado, <strong>só com CPU e RAM</strong> (PyTorch CPU, containers independentes). Depois, o Blender normaliza escala/pivô, reduz polígonos, gera LODs e exporta GLB/FBX/BLEND. O estilo
          “Premium Stylized” vem da imagem de referência que você fornece. Texto→3D exige um modelo de texto→imagem e não está habilitado.
        </div>
        <Panel title="1 · Modelo de geração">
          <div className="grid g2">
            {Object.entries(PROVIDERS).map(([k, p]) => (
              <label key={k} className="card" style={{ padding: 12, cursor: "pointer", outline: provider === k ? "2px solid var(--accent)" : undefined }}>
                <div className="row">
                  <input type="radio" name="provider" checked={provider === k} onChange={() => setProvider(k as "sf3d" | "triposr")} />
                  <strong>{p.title}</strong>
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{p.blurb}</div>
                <div style={{ fontSize: 11, marginTop: 6 }} className={k === "sf3d" ? "check-warn" : "muted"}>
                  {p.license}
                </div>
              </label>
            ))}
          </div>
        </Panel>
        <Panel title="2 · Imagem de referência">
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div>
              <label className="btn">
                <Upload size={14} /> Enviar imagem (PNG/JPEG/WEBP, 64–4096 px)
                <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              </label>
              {ref && <span className="chip" style={{ marginLeft: 8 }}>{ref.id} · {ref.width}×{ref.height}</span>}
              {upErr && <div className="error-note">{upErr}</div>}
              <p className="muted" style={{ fontSize: 11 }}>Um único objeto, bem visível, em fundo liso. O fundo é removido automaticamente (rembg).</p>
            </div>
            {refUrl && <img src={refUrl} alt="Referência enviada" style={{ width: 120, height: 120, objectFit: "contain", background: "var(--panel-2)", borderRadius: 6 }} />}
          </div>
        </Panel>
        <Panel title="3 · Asset, qualidade e otimização">
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
              Resolução da textura
              <select value={tex} onChange={(e) => setTex(e.target.value)}>
                <option value="">do perfil</option>
                {[512, 1024, 2048].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </label>
            {provider === "triposr" ? (
              <label className="field">
                Marching cubes (detalhe da malha)
                <select value={mc} onChange={(e) => setMc(e.target.value)}>
                  <option value="">do perfil</option>
                  {[192, 256, 320, 384].map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="field">
                Remalhamento (SF3D)
                <select value={remesh} onChange={(e) => setRemesh(e.target.value)}>
                  <option value="none">nenhum</option>
                  <option value="triangle">triângulos</option>
                  <option value="quad">quads</option>
                </select>
              </label>
            )}
            <label className="field">
              Máx. triângulos do LOD0
              <input type="number" min={200} value={maxTris} placeholder="orçamento da categoria" onChange={(e) => setMaxTris(e.target.value)} />
            </label>
            <label className="field">
              LODs (razões)
              <input value={lods} onChange={(e) => setLods(e.target.value)} aria-invalid={!lodList} />
              {!lodList && <span className="check-fail">decrescente, entre 0,02 e 1</span>}
            </label>
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
            <div className="check-ok">✔ {capable.map((w) => w.name).join(", ")} com {PROVIDERS[provider].title}</div>
          ) : (
            <div className="error-note">Nenhum worker oferece este modelo agora; o job ficaria na fila.</div>
          )}
          {!capable.length && status.map((s, i) => <div key={i} className="muted" style={{ fontSize: 12 }}>{s?.reason}</div>)}
          <p className="muted" style={{ fontSize: 11 }}>
            Threads, RAM e concorrência: limites do worker (aba Workers) e do container (.env). Resultados de tempo e RAM aparecem no manifesto e no benchmark — nada é estimado aqui.
          </p>
          <ErrorNote error={submit.error} />
          <button className="primary" style={{ width: "100%", justifyContent: "center" }} disabled={!ready || submit.isPending} onClick={() => submit.mutate()}>
            <Sparkles size={15} /> Gerar modelo 3D
          </button>
        </Panel>
      </div>
    </div>
  );
}
