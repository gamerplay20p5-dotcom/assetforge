import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, ChevronDown, Download, Grid3x3, ImagePlus, Maximize2, Package, RotateCw, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, fileUrl, getToken, packageUrl, useDownloadToken } from "../api";
import { GenAnimation } from "../components/GenAnimation";
import { Viewer3D, type ViewerStats } from "../components/Viewer3D";
import { ErrorNote, Thumb } from "../components/ui";
import { MAX_IMAGE_MB, PRESETS, PROVIDERS, STAGE_LABEL, checkImageFile, parseLods, type PresetKey } from "../imageTo3d";
import { formatDuration, timeAgo } from "../lib";
import type { Asset, Job, Worker } from "../types";

interface Item {
  key: string;
  file: File;
  url: string;
  error: string | null;
}

const ACTIVE = new Set(["queued", "running"]);

export function Studio() {
  const qc = useQueryClient();
  const token = useDownloadToken();
  const input = useRef<HTMLInputElement>(null);

  // ---- generate form
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const [preset, setPreset] = useState<PresetKey>("mid");
  const [tris, setTris] = useState<number>(PRESETS.mid.tris);
  const [size, setSize] = useState(2);
  const [provider, setProvider] = useState<"triposr" | "sf3d">("triposr");
  const [tex, setTex] = useState<number>(PRESETS.mid.tex);
  const [lods, setLods] = useState<string>(PRESETS.mid.lods.join(", "));
  const [category, setCategory] = useState("prop");
  const [formats, setFormats] = useState<string[]>(["glb", "fbx", "blend"]);
  const [more, setMore] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);

  // ---- stage / viewer
  const [jobId, setJobId] = useState<string | null>(null);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [lod, setLod] = useState(0);
  const [wire, setWire] = useState(false);
  const [bounds, setBounds] = useState(false);
  const [rotate, setRotate] = useState(true);
  const [stats, setStats] = useState<ViewerStats | null>(null);
  const [tab, setTab] = useState<"assets" | "props">("assets");

  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 8000 });
  const online = (workers.data ?? []).filter((w) => w.online && w.state === "enabled");
  const upFor = (p: string) => online.some((w) => w.capabilities.features?.includes(`provider.${p}`));
  const providerUp = upFor(provider);
  const reasonFor = (p: string) => (workers.data ?? []).map((w) => w.capabilities.cpu3d?.providers?.[p]?.reason).find(Boolean);
  const providerWhy = reasonFor(provider);
  // never leave an unavailable model selected: jump to one that a worker can actually run
  const triUp = upFor("triposr");
  const sfUp = upFor("sf3d");
  useEffect(() => {
    if (!workers.data) return;
    if (provider === "sf3d" && !sfUp && triUp) setProvider("triposr");
    if (provider === "triposr" && !triUp && sfUp) setProvider("sf3d");
  }, [workers.data, provider, sfUp, triUp]);
  const lodList = parseLods(lods);

  const jobs = useQuery({ queryKey: ["jobs", "studio"], queryFn: () => api<{ items: Job[] }>("/jobs?limit=30"), refetchInterval: 4000 });
  const running = (jobs.data?.items ?? []).filter((j) => ACTIVE.has(j.status));
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api<Job>(`/jobs/${jobId}`), enabled: !!jobId, refetchInterval: 1500 });
  const assets = useQuery({ queryKey: ["assets", "studio"], queryFn: () => api<{ total: number; items: Asset[] }>("/assets?limit=60&sort=-created_at"), refetchInterval: 6000 });
  const asset = useQuery({ queryKey: ["asset", assetId], queryFn: () => api<Asset>(`/assets/${assetId}`), enabled: !!assetId });
  const a = asset.data;
  const m = a?.manifest;

  // when the watched job ends, show its asset
  const j = job.data;
  useEffect(() => {
    if (j?.status === "succeeded") {
      setAssetId(j.asset_id);
      setJobId(null);
      setLod(0);
      setTab("props");
      qc.invalidateQueries({ queryKey: ["assets"] });
    }
  }, [j?.status, j?.asset_id, qc]);

  const pick = (k: PresetKey) => {
    setPreset(k);
    const p = PRESETS[k];
    setTris(p.tris);
    setTex(p.tex);
    setLods(p.lods.join(", "));
  };
  const add = (files: FileList | File[]) => {
    const next = Array.from(files).map((f) => ({ key: `${f.name}-${f.size}-${f.lastModified}-${Math.random()}`, file: f, url: URL.createObjectURL(f), error: checkImageFile(f) }));
    setItems((cur) => [...cur, ...next]);
  };
  const valid = items.filter((i) => !i.error);

  const upload = async (file: File): Promise<string> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/v1/references", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `falha no upload (${res.status})`);
    return body.id as string;
  };
  const generate = useMutation({
    mutationFn: async () => {
      const p = PRESETS[preset];
      const ids: string[] = [];
      for (const [n, it] of valid.entries()) {
        setProgress(`Enviando ${n + 1}/${valid.length}…`);
        const ref = await upload(it.file);
        const created = await api<{ id: string }>("/jobs", {
          method: "POST",
          json: {
            name: it.file.name.replace(/\.[^.]+$/, "").slice(0, 80) || "Asset",
            job_type: "ai.image_to_3d",
            quality_profile: p.profile,
            formats,
            params: { provider, reference_id: ref, category, target_size_m: size, lod_ratios: lodList ?? [], texture_resolution: tex, max_triangles: tris },
          },
        });
        ids.push(created.id);
      }
      return ids;
    },
    onSuccess: (ids) => {
      setItems([]);
      setAssetId(null);
      setJobId(ids[0] ?? null);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onSettled: () => setProgress(null),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/jobs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["job"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const ready = valid.length > 0 && tris >= 200 && tris <= 200000 && !!lodList && size > 0;

  const ver = a?.version_info?.version ?? a?.current_version;
  const lodFile = m?.lods?.[lod]?.file ?? "model.glb";
  const glb = a && token ? fileUrl(a.id, lodFile, token, ver) : null;
  const generating = !!j && ACTIVE.has(j.status);
  const failed = !!j && (j.status === "failed" || j.status === "cancelled");
  const needed = (j?.requirements?.features ?? []).find((f) => f.startsWith("provider."))?.slice(9);
  const stuck = j?.status === "queued" && !!needed && !upFor(needed);
  const stageName = j?.current_stage ? (STAGE_LABEL[j.current_stage] ?? j.current_stage) : stuck ? `Nenhum worker oferece o modelo ${PROVIDERS[needed as keyof typeof PROVIDERS]?.title ?? needed} agora` : j?.status === "queued" ? "Na fila, aguardando um worker livre" : "Iniciando";
  const elapsed = useMemo(() => (j?.started_at ? Math.max(0, (Date.now() - new Date(j.started_at).getTime()) / 1000) : null), [j?.started_at, j?.progress]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="studio">
      {/* ------------------------------------------------ generate panel */}
      <aside className="st-left">
        <div className="st-title"><Sparkles size={16} /> Gerar modelo 3D</div>

        <div className="seg" role="radiogroup" aria-label="Nível de polígonos">
          {(Object.keys(PRESETS) as PresetKey[]).map((k) => (
            <button key={k} role="radio" aria-checked={preset === k} className={preset === k ? "on" : ""} onClick={() => pick(k)}>
              {PRESETS[k].label}
            </button>
          ))}
        </div>
        <div className="st-hint">
          {preset === "custom" ? "Defina o número de triângulos abaixo." : `${PRESETS[preset].hint} · ~${PRESETS[preset].tris.toLocaleString("pt-BR")} triângulos`}
        </div>

        <div
          className={`dropzone ${over ? "over" : ""} ${items.length ? "has" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="Escolher imagens de referência"
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
        >
          {items.length === 0 ? (
            <>
              <ImagePlus size={30} />
              <strong>Enviar imagem</strong>
              <span>Arraste ou clique · PNG, JPG, WEBP · até {MAX_IMAGE_MB} MB</span>
            </>
          ) : (
            <div className="drop-grid" onClick={(e) => e.stopPropagation()}>
              {items.map((i) => (
                <div key={i.key} className={`drop-item ${i.error ? "bad" : ""}`} title={i.error ?? i.file.name}>
                  <img src={i.url} alt={i.file.name} />
                  <button className="icon x" aria-label={`Remover ${i.file.name}`} onClick={() => setItems((c) => c.filter((x) => x.key !== i.key))}>
                    <X size={12} />
                  </button>
                  {i.error && <span className="drop-err">{i.error}</span>}
                </div>
              ))}
              <button className="drop-add" onClick={() => input.current?.click()} aria-label="Adicionar mais imagens">
                <ImagePlus size={18} />
              </button>
            </div>
          )}
          <input
            ref={input}
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={(e) => {
              if (e.target.files) add(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        <div className="st-hint">Um objeto por imagem, fundo liso. Cada imagem vira um modelo.</div>

        <button className="st-acc" aria-expanded={more} onClick={() => setMore(!more)}>
          Configurações gerais <ChevronDown size={16} style={{ transform: more ? "rotate(180deg)" : undefined, transition: "transform .2s" }} />
        </button>
        {more && (
          <div className="st-fields">
            <label className="field">Triângulos (LOD0)
              <input type="number" min={200} max={200000} step={100} value={tris} onChange={(e) => { setTris(Number(e.target.value)); setPreset("custom"); }} />
            </label>
            <label className="field">Altura real (m)
              <input type="number" min={0.1} step={0.5} value={size} onChange={(e) => setSize(Number(e.target.value))} />
            </label>
            <label className="field">Textura
              <select value={tex} onChange={(e) => setTex(Number(e.target.value))}>
                {[256, 512, 1024, 2048].map((r) => <option key={r} value={r}>{r} px</option>)}
              </select>
            </label>
            <label className="field">LODs (razões)
              <input value={lods} onChange={(e) => setLods(e.target.value)} aria-invalid={!lodList} />
              {!lodList && <span className="check-fail">decrescente, entre 0,02 e 1</span>}
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Modelo de IA
              <select value={provider} onChange={(e) => setProvider(e.target.value as "triposr" | "sf3d")}>
                {Object.entries(PROVIDERS).map(([k, p]) => <option key={k} value={k} disabled={!upFor(k)}>{p.title} — {upFor(k) ? p.note : "indisponível agora"}</option>)}
              </select>
            </label>
            <label className="field">Categoria
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                {["prop", "house", "commercial", "industrial", "vehicle", "character", "tree"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
            <div className="field" style={{ gridColumn: "1 / -1" }}>Formatos
              <div className="row wrap" style={{ gap: 14 }}>
                <span className="check muted">GLB (sempre)</span>
                {["fbx", "blend"].map((f) => (
                  <label key={f} className="check">
                    <input type="checkbox" checked={formats.includes(f)} onChange={(e) => setFormats(e.target.checked ? [...formats, f] : formats.filter((x) => x !== f))} />
                    {f.toUpperCase()}
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="st-foot">
          {!providerUp && (
            <div className="st-warn">
              {PROVIDERS[provider].title} indisponível agora; o job ficaria na fila.{providerWhy ? ` ${providerWhy}` : ""}
            </div>
          )}
          {progress && <div className="st-hint">{progress}</div>}
          <ErrorNote error={generate.error} />
          <button className="st-generate" disabled={!ready || generate.isPending} onClick={() => generate.mutate()}>
            <Sparkles size={18} />
            {generate.isPending ? "Enviando…" : valid.length > 1 ? `Gerar ${valid.length} modelos` : "Gerar modelo"}
            <span className="st-cost">~{tris.toLocaleString("pt-BR")} △</span>
          </button>
        </div>
      </aside>

      {/* ------------------------------------------------ stage */}
      <section className="st-stage">
        {generating && j ? (
          <div className="st-gen">
            <GenAnimation progress={j.progress} />
            <div className="st-gen-info">
              <div className="st-pct">{Math.round(j.progress * 100)}<small>%</small></div>
              <div className="st-stage-name" aria-live="polite">{stageName}</div>
              <div className="st-bar"><i style={{ width: `${Math.max(2, j.progress * 100)}%` }} /></div>
              <div className="st-sub">
                {j.name}
                {elapsed != null && ` · ${formatDuration(elapsed)}`}
                {j.eta_seconds ? ` · restam ~${formatDuration(j.eta_seconds)}` : ""}
              </div>
              {stuck && <div className="st-warn" style={{ maxWidth: 420 }}>Este pedido não vai andar: {reasonFor(needed!) ?? "o modelo não está pronto em nenhum worker"}. Cancele e gere de novo com {triUp ? "o TripoSR" : "outro modelo"}.</div>}
              <button onClick={() => cancel.mutate(j.id)} disabled={cancel.isPending}>Cancelar</button>
              <div className="st-sub dim">A animação é ilustrativa; o percentual e a etapa vêm do job real.</div>
            </div>
          </div>
        ) : failed && j ? (
          <div className="st-empty">
            <div className="st-logo err"><X size={34} /></div>
            <h2>{j.status === "cancelled" ? "Geração cancelada" : "A geração falhou"}</h2>
            <p>{j.error ?? "Veja os detalhes na fila."}</p>
            <div className="row">
              <Link className="btn" to="/queue">Abrir fila</Link>
              <button onClick={() => setJobId(null)}>Fechar</button>
            </div>
          </div>
        ) : a ? (
          <>
            <Viewer3D url={glb} wireframe={wire} showBounds={bounds} autoRotate={rotate} studio onStats={setStats} />
            <div className="st-tools" role="toolbar" aria-label="Ferramentas do visualizador">
              <button className={wire ? "on" : ""} onClick={() => setWire(!wire)} title="Wireframe" aria-pressed={wire}><Grid3x3 size={17} /></button>
              <button className={bounds ? "on" : ""} onClick={() => setBounds(!bounds)} title="Caixa delimitadora" aria-pressed={bounds}><Box size={17} /></button>
              <button className={rotate ? "on" : ""} onClick={() => setRotate(!rotate)} title="Girar automaticamente" aria-pressed={rotate}><RotateCw size={17} /></button>
              <Link className="btn tool" to={`/library/${a.id}`} title="Abrir na biblioteca"><Maximize2 size={17} /></Link>
            </div>
            <div className="st-caption">
              <strong>{a.name}</strong>
              {stats && <span className="chip">{stats.triangles.toLocaleString("pt-BR")} △</span>}
              {stats && <span className="chip">{stats.size.map((v) => v.toFixed(2)).join(" × ")} m</span>}
              {(m?.lods?.length ?? 0) > 1 && (
                <select aria-label="Nível de detalhe" value={lod} onChange={(e) => setLod(Number(e.target.value))}>
                  {m!.lods.map((x, i) => <option key={x.file} value={i}>LOD{x.level} · {x.triangles.toLocaleString("pt-BR")} △</option>)}
                </select>
              )}
            </div>
          </>
        ) : (
          <div className="st-empty">
            <div className="st-logo"><Box size={36} /></div>
            <h2>Pronto para um novo modelo 3D?</h2>
            <p>Envie uma imagem de referência, escolha Low ou Mid poly e clique em Gerar.</p>
          </div>
        )}
      </section>

      {/* ------------------------------------------------ assets / properties */}
      <aside className="st-right">
        <div className="st-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "assets"} className={tab === "assets" ? "on" : ""} onClick={() => setTab("assets")}>Assets</button>
          <button role="tab" aria-selected={tab === "props"} className={tab === "props" ? "on" : ""} onClick={() => setTab("props")}>Propriedades</button>
        </div>
        {tab === "assets" ? (
          <div className="st-scroll">
            {running.length > 0 && (
              <div className="st-section">
                <div className="st-label">Em geração</div>
                {running.map((r) => (
                  <button key={r.id} className={`st-job ${jobId === r.id ? "on" : ""}`} onClick={() => { setAssetId(null); setJobId(r.id); }}>
                    <span className="spin" />
                    <span className="st-job-name">{r.name}</span>
                    <span className="mono">{r.status === "queued" ? "fila" : `${Math.round(r.progress * 100)}%`}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="st-label">Seus assets {assets.data ? `(${assets.data.total})` : ""}</div>
            {(assets.data?.items ?? []).length === 0 ? (
              <div className="st-hint">{assets.isLoading ? "Carregando…" : "Nenhum asset ainda."}</div>
            ) : (
              <div className="st-cards">
                {(assets.data?.items ?? []).map((x) => (
                  <button key={x.id} className={`st-card ${assetId === x.id ? "on" : ""}`} onClick={() => { setJobId(null); setAssetId(x.id); setLod(0); }}>
                    <Thumb assetId={x.id} alt={x.name} hasThumb={x.has_thumbnail} />
                    <span className="st-card-name">{x.name}</span>
                    <span className="st-card-sub">{x.triangle_count.toLocaleString("pt-BR")} △</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="st-scroll">
            {!a ? (
              <div className="st-hint">Selecione ou gere um asset para ver as propriedades.</div>
            ) : (
              <>
                <div className="st-prop-title">{a.name} <span className="mono muted">v{ver}</span></div>
                <dl className="st-props">
                  <dt>Triângulos</dt><dd>{a.triangle_count.toLocaleString("pt-BR")}</dd>
                  {a.dimensions_m && (<><dt>Dimensões</dt><dd>{a.dimensions_m.map((v) => v.toFixed(2)).join(" × ")} m</dd></>)}
                  <dt>Perfil</dt><dd>{m?.quality_profile ?? "—"}</dd>
                  <dt>Materiais</dt><dd>{m?.materials?.length ?? 0} · {m?.textures?.length ?? 0} textura(s)</dd>
                  <dt>Validação</dt><dd className={a.validation_passed ? "check-ok" : "check-fail"}>{a.validation_passed ? "aprovada" : "com problemas"}</dd>
                  <dt>Licença</dt><dd>{m?.license ?? "—"}</dd>
                  <dt>Criado</dt><dd>{timeAgo(a.created_at)}</dd>
                </dl>
                {(m?.lods?.length ?? 0) > 0 && (
                  <>
                    <div className="st-label">LODs</div>
                    <div className="st-lods">
                      {m!.lods.map((x, i) => (
                        <button key={x.file} className={lod === i ? "on" : ""} onClick={() => setLod(i)}>LOD{x.level}<small>{x.triangles.toLocaleString("pt-BR")} △</small></button>
                      ))}
                    </div>
                  </>
                )}
                <div className="st-label">Baixar</div>
                <div className="row wrap">
                  <a className="btn" href={fileUrl(a.id, "model.glb", token, ver, true)}><Download size={14} /> GLB</a>
                  {a.files?.some((f) => f.format === "fbx") && <a className="btn" href={fileUrl(a.id, "model.fbx", token, ver, true)}><Download size={14} /> FBX</a>}
                  {a.files?.some((f) => f.format === "blend") && <a className="btn" href={fileUrl(a.id, "model.blend", token, ver, true)}><Download size={14} /> BLEND</a>}
                  <a className="btn" href={packageUrl(a.id, token, ver)}><Package size={14} /> ZIP</a>
                </div>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
