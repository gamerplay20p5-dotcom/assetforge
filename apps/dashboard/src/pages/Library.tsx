import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Grid3x3, Heart, List, Package, RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, fileUrl, getToken, packageUrl, useDownloadToken } from "../api";
import { Viewer3D, type ViewerStats } from "../components/Viewer3D";
import { AssetComparison } from "../components/AssetComparison";
import { Empty, ErrorNote, Panel, Thumb } from "../components/ui";
import { formatBytes, timeAgo } from "../lib";
import type { Asset } from "../types";

const REVIEW: Record<string, string> = { pending: "Pendente", approved: "Aprovado", rejected: "Rejeitado" };

export function Library() {
  const { assetId } = useParams();
  const nav = useNavigate();
  const [view, setView] = useState<"grid" | "list">("grid");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [review, setReview] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [sort, setSort] = useState("-created_at");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = `/assets?limit=200&sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ""}${category ? `&category=${category}` : ""}${review ? `&review_status=${review}` : ""}${favOnly ? "&favorite=true" : ""}`;
  const list = useQuery({ queryKey: ["assets", query], queryFn: () => api<{ total: number; items: Asset[]; facets: { category: Record<string, number> } }>(query), refetchInterval: 8000 });
  const items = list.data?.items ?? [];
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const downloadZip = async () => {
    const res = await fetch("/api/v1/assets/download", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ asset_ids: [...selected], include: "package" }),
    });
    if (!res.ok) return alert(`Falha no download: ${res.status}`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = "assetforge_assets.zip";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className={`lib-layout ${assetId ? "" : "no-detail"}`}>
      <div className="grid" style={{ gap: 12, minWidth: 0 }}>
        <div className="row wrap">
          <input style={{ width: 240 }} placeholder="Buscar por nome, id, categoria…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar assets" />
          <select style={{ width: 170 }} value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Categoria">
            <option value="">todas as categorias</option>
            {Object.entries(list.data?.facets.category ?? {}).map(([c, n]) => (
              <option key={c} value={c}>
                {c} ({n})
              </option>
            ))}
          </select>
          <select style={{ width: 140 }} value={review} onChange={(e) => setReview(e.target.value)} aria-label="Revisão">
            <option value="">qualquer revisão</option>
            {Object.entries(REVIEW).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select style={{ width: 150 }} value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Ordenar">
            <option value="-created_at">mais recentes</option>
            <option value="name">nome</option>
            <option value="-triangle_count">mais triângulos</option>
            <option value="triangle_count">menos triângulos</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={favOnly} onChange={(e) => setFavOnly(e.target.checked)} /> favoritos
          </label>
          <div className="spacer" />
          <span className="muted">{list.data?.total ?? 0} assets</span>
          <button className="icon" onClick={() => setView(view === "grid" ? "list" : "grid")} aria-label="Alternar grade/lista" title="Alternar grade/lista">
            {view === "grid" ? <List size={15} /> : <Grid3x3 size={15} />}
          </button>
          <button disabled={!selected.size} onClick={downloadZip}>
            <Package size={14} /> Baixar {selected.size || ""} (ZIP)
          </button>
        </div>
        {items.length === 0 ? (
          <Empty>{list.isLoading ? "Carregando…" : "Nenhum asset encontrado."}</Empty>
        ) : view === "grid" ? (
          <div className="cards">
            {items.map((a) => (
              <div key={a.id} className={`card ${assetId === a.id ? "selected" : ""}`} onClick={() => nav(`/library/${a.id}`)}>
                <Thumb assetId={a.id} alt={a.name} hasThumb={a.has_thumbnail} />
                <div className="corner">
                  {a.favorite && <span className="chip">♥</span>}
                  {a.review_status !== "pending" && <span className={`chip ${a.review_status === "approved" ? "check-ok" : "check-fail"}`}>{REVIEW[a.review_status]}</span>}
                </div>
                <input className="check-box" type="checkbox" checked={selected.has(a.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(a.id)} aria-label={`Selecionar ${a.name}`} />
                <div className="meta">
                  <div className="title">{a.name}</div>
                  <div className="sub">
                    <span>{a.category}</span>
                    <span>{a.triangle_count.toLocaleString()} △</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Panel>
            <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>Nome</th>
                    <th>Categoria</th>
                    <th>Triângulos</th>
                    <th>Dimensões (m)</th>
                    <th>Versão</th>
                    <th>Revisão</th>
                    <th>Criado</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => (
                    <tr key={a.id} className={`clickable ${assetId === a.id ? "selected" : ""}`} onClick={() => nav(`/library/${a.id}`)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggle(a.id)} aria-label={`Selecionar ${a.name}`} />
                      </td>
                      <td>
                        {a.favorite ? "♥ " : ""}
                        {a.name}
                        <div className="muted mono">{a.id}</div>
                      </td>
                      <td>{a.category}</td>
                      <td className="mono">{a.triangle_count.toLocaleString()}</td>
                      <td className="mono">{a.dimensions_m?.map((d) => d.toFixed(1)).join(" × ") ?? "—"}</td>
                      <td>v{a.current_version}</td>
                      <td>{REVIEW[a.review_status]}</td>
                      <td className="muted">{timeAgo(a.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
      {assetId && <AssetDetail id={assetId} onClose={() => nav("/library")} />}
    </div>
  );
}

function AssetDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const token = useDownloadToken();
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<"preview" | "compare" | "info" | "validation" | "versions" | "files">("preview");
  const [wire, setWire] = useState(false);
  const [bounds, setBounds] = useState(false);
  const [rotate, setRotate] = useState(false);
  const [stats, setStats] = useState<ViewerStats | null>(null);
  const [lod, setLod] = useState(0);
  const asset = useQuery({ queryKey: ["asset", id, version], queryFn: () => api<Asset>(`/assets/${id}${version ? `?version=${version}` : ""}`) });
  const a = asset.data;
  const patch = useMutation({
    mutationFn: (b: Record<string, unknown>) => api(`/assets/${id}${version && b.review_status ? `?version=${version}` : ""}`, { method: "PATCH", json: b }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["asset", id] });
      qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const regen = useMutation({
    mutationFn: async () => {
      if (!a?.manifest) throw new Error("sem manifesto");
      const seedText = window.prompt("Seed para a nova versão (vazio = mesma seed)", String(a.seed ?? ""));
      if (seedText === null) return null;
      const { summary: _s, ...params } = a.manifest.generation_params as Record<string, unknown>;
      void _s;
      if (seedText.trim()) params.seed = Number(seedText);
      const formats = [...new Set((a.files ?? []).filter((f) => ["glb", "blend", "fbx"].includes(f.format) && f.role !== "texture").map((f) => f.format))];
      return api("/jobs", { method: "POST", json: { name: a.name, asset_id: a.id, params, quality_profile: a.manifest.quality_profile, formats } });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  if (asset.error instanceof ApiError && asset.error.status === 404) return <Panel title="Asset"><Empty>Asset não encontrado.</Empty></Panel>;
  if (!a) return <Panel title="Asset"><Empty>Carregando…</Empty></Panel>;
  const m = a.manifest;
  const ver = a.version_info?.version ?? a.current_version;
  const lodFile = m?.lods?.[lod]?.file ?? "model.glb";
  const glb = token ? fileUrl(a.id, lodFile, token, ver) : null;
  const over = m?.triangle_budget && stats ? stats.triangles > m.triangle_budget[1] : false;
  return (
    <Panel
      title={
        <span>
          {a.name} <span className="muted mono">v{ver}</span>
        </span>
      }
      actions={
        <button className="icon ghost" onClick={onClose} aria-label="Fechar detalhe">
          <X size={15} />
        </button>
      }
    >
      <div className="tabs" role="tablist">
        {(
          [
            ["preview", "Preview 3D"],
            ["compare", "Comparar"],
            ["info", "Geometria e materiais"],
            ["validation", "Validação"],
            ["versions", "Versões"],
            ["files", "Arquivos"],
          ] as const
        ).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>
      {tab === "compare" && <AssetComparison key={`${id}-${ver}`} asset={a} version={ver} token={token} />}
      {tab === "preview" && (
        <>
          <Viewer3D url={glb} wireframe={wire} showBounds={bounds} autoRotate={rotate} onStats={setStats} />
          <div className="row wrap" style={{ marginTop: 8 }}>
            <label className="check">
              <input type="checkbox" checked={wire} onChange={(e) => setWire(e.target.checked)} /> Wireframe
            </label>
            <label className="check">
              <input type="checkbox" checked={bounds} onChange={(e) => setBounds(e.target.checked)} /> Bounding box
            </label>
            <label className="check">
              <input type="checkbox" checked={rotate} onChange={(e) => setRotate(e.target.checked)} /> Girar
            </label>
            {(m?.lods?.length ?? 0) > 1 && (
              <label className="check">
                LOD
                <select style={{ width: 150 }} value={lod} onChange={(e) => setLod(Number(e.target.value))} aria-label="Nível de detalhe">
                  {m!.lods.map((x, i) => (
                    <option key={i} value={i}>
                      LOD{x.level} · {x.triangles.toLocaleString()} △
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {stats && (
            <div className="row wrap muted" style={{ marginTop: 6, fontSize: 12 }}>
              <span className={over ? "check-warn" : ""}>{stats.triangles.toLocaleString()} triângulos {m?.triangle_budget ? `(orçamento ${m.triangle_budget.join("–")})` : ""}</span>
              <span>· {stats.size.map((s) => s.toFixed(1)).join(" × ")} m</span>
              <span>· {stats.meshes} malhas/materiais</span>
            </div>
          )}
        </>
      )}
      {tab === "info" && m && (
        <div className="grid" style={{ gap: 12 }}>
          <dl className="kv">
            <dt>Categoria</dt>
            <dd>{a.category}</dd>
            <dt>Dimensões</dt>
            <dd>{a.dimensions_m?.map((d) => d.toFixed(2)).join(" × ")} m (L×A×P)</dd>
            <dt>Pivô</dt>
            <dd>{m.generator_id === "experimental.reconstruct" ? "Sistema de coordenadas original do motor" : "Centro da base (Y-up)"}</dd>
            <dt>Triângulos</dt>
            <dd>
              {m.triangle_count.toLocaleString()} (LOD0){m.triangle_budget && ` · orçamento ${m.triangle_budget.join("–")}`}
            </dd>
            <dt>Gerador</dt>
            <dd className="mono">
              {m.generator_id}@{m.generator_version} · seed {a.seed}
            </dd>
            <dt>Motor de export</dt>
            <dd>{a.engine}</dd>
            <dt>Perfil visual</dt>
            <dd>{a.art_profile}</dd>
            <dt>Licença</dt>
            <dd>{m.license}</dd>
            <dt>LODs</dt>
            <dd>{m.lods.map((l) => `LOD${l.level}: ${l.triangles}`).join(", ")} (LODs adicionais: Milestone 3)</dd>
            <dt>Colisão</dt>
            <dd>{m.colliders.map((c) => `${c.type} ${c.size.map((s) => s.toFixed(1)).join("×")}`).join(", ")}</dd>
            <dt>Pontos de conexão</dt>
            <dd>{m.connection_points.map((c) => c.name).join(", ") || "—"}</dd>
          </dl>
          <div>
            <h4 style={{ margin: "0 0 6px" }}>Materiais</h4>
            <div className="row wrap">
              {m.materials.map((mt) => (
                <span className="chip" key={mt.name} title={`${mt.texture ?? "cor lisa"} · rugosidade ${mt.roughness} · metal ${mt.metallic}`}>
                  <span className="swatch" style={{ background: mt.base_color }} />
                  {mt.name}
                </span>
              ))}
            </div>
          </div>
          <div>
            <h4 style={{ margin: "0 0 6px" }}>Texturas</h4>
            <div className="row wrap">
              {token &&
                m.textures.map((t) => (
                  <a key={t} href={fileUrl(a.id, t, token, ver)} target="_blank" rel="noreferrer" title={t}>
                    <img alt={t} src={fileUrl(a.id, t, token, ver)} width={64} height={64} style={{ borderRadius: 4, border: "1px solid var(--border)" }} />
                  </a>
                ))}
            </div>
          </div>
          <p className="note">Edição de escala, rotação, pivô, materiais e geometria (Asset Inspector) chega no Milestone 3; operações destrutivas criarão novas versões.</p>
        </div>
      )}
      {tab === "validation" && a.validation && (
        <div className="grid" style={{ gap: 6 }}>
          <div className={a.validation.passed ? "check-ok" : "check-fail"}>{a.validation.passed ? "✔ Validação aprovada" : "✘ Validação reprovada"}</div>
          {a.validation.checks.map((c, i) => (
            <div key={i} className={`check-${c.status === "pass" ? "ok" : c.status}`} style={{ fontSize: 12 }}>
              {c.status === "pass" ? "✔" : c.status === "warn" ? "⚠" : "✘"} <strong>{c.name}</strong> <span className="muted">{c.detail}</span>
            </div>
          ))}
        </div>
      )}
      {tab === "versions" && (
        <table>
          <thead>
            <tr>
              <th>Versão</th>
              <th>Triângulos</th>
              <th>Motor</th>
              <th>Criada</th>
            </tr>
          </thead>
          <tbody>
            {(a.versions ?? []).slice().reverse().map((v) => (
              <tr key={v.version} className="clickable" onClick={() => setVersion(v.version)}>
                <td>
                  v{v.version} {v.version === a.current_version && <span className="chip">atual</span>} {v.version === ver && <span className="chip">vendo</span>}
                </td>
                <td className="mono">{v.triangle_count.toLocaleString()}</td>
                <td>{v.engine}</td>
                <td className="muted">{timeAgo(v.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tab === "files" && (
        <table>
          <tbody>
            {(a.files ?? []).map((f) => (
              <tr key={f.name}>
                <td>
                  <a href={fileUrl(a.id, f.name, token, ver, true)}>{f.name}</a>
                  <div className="muted mono" title={f.sha256}>
                    sha256 {f.sha256.slice(0, 16)}…
                  </div>
                </td>
                <td>{f.role}</td>
                <td className="mono">{formatBytes(f.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <hr style={{ border: 0, borderTop: "1px solid var(--border)", margin: "14px 0" }} />
      <ErrorNote error={patch.error ?? regen.error} />
      <div className="row wrap">
        <button className={a.review_status === "approved" ? "primary" : ""} onClick={() => patch.mutate({ review_status: a.review_status === "approved" ? "pending" : "approved" })}>
          <Check size={14} /> Aprovar
        </button>
        <button className={a.review_status === "rejected" ? "danger" : ""} onClick={() => patch.mutate({ review_status: a.review_status === "rejected" ? "pending" : "rejected" })}>
          <X size={14} /> Rejeitar
        </button>
        <button onClick={() => patch.mutate({ favorite: !a.favorite })} aria-pressed={a.favorite}>
          <Heart size={14} fill={a.favorite ? "currentColor" : "none"} /> Favorito
        </button>
        {m?.generator_id === "experimental.reconstruct" ? <Link className="btn"
          to={`/engines?asset=${encodeURIComponent(a.id)}&name=${encodeURIComponent(a.name)}`}>
          <RefreshCw size={14} /> Nova versão
        </Link> : <button onClick={() => regen.mutate()} disabled={regen.isPending}>
          <RefreshCw size={14} /> Nova versão
        </button>}
      </div>
      <div className="row wrap" style={{ marginTop: 8 }}>
        <a className="btn" href={fileUrl(a.id, "model.glb", token, ver, true)}>
          <Download size={14} /> GLB
        </a>
        {a.files?.some((f) => f.format === "fbx") && (
          <a className="btn" href={fileUrl(a.id, "model.fbx", token, ver, true)}>
            <Download size={14} /> FBX
          </a>
        )}
        {a.files?.some((f) => f.format === "blend") && (
          <a className="btn" href={fileUrl(a.id, "model.blend", token, ver, true)}>
            <Download size={14} /> BLEND
          </a>
        )}
        <a className="btn" href={packageUrl(a.id, token, ver)}>
          <Package size={14} /> Pacote ZIP
        </a>
      </div>
      <div className="row wrap" style={{ marginTop: 10 }}>
        {a.tags.map((t) => (
          <span key={t} className="chip">
            #{t}{" "}
            <button className="ghost icon" style={{ padding: 0, border: 0 }} aria-label={`Remover tag ${t}`} onClick={() => patch.mutate({ tags: a.tags.filter((x) => x !== t) })}>
              ×
            </button>
          </span>
        ))}
        <input
          style={{ width: 130 }}
          placeholder="+ tag (Enter)"
          onKeyDown={(e) => {
            const v = (e.target as HTMLInputElement).value.trim();
            if (e.key === "Enter" && v) {
              patch.mutate({ tags: [...a.tags, v] });
              (e.target as HTMLInputElement).value = "";
            }
          }}
        />
      </div>
    </Panel>
  );
}
