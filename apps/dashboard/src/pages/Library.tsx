import { useLocale, type Translate } from "../i18n";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Grid3x3, Heart, List, Package, RefreshCw, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, fileUrl, getToken, packageUrl, useDownloadToken } from "../api";
import { Viewer3D, type ViewerStats } from "../components/Viewer3D";
import { AssetComparison } from "../components/AssetComparison";
import { OptimizationComparison } from "../components/OptimizationComparison";
import { Empty, ErrorNote, Panel, Thumb } from "../components/ui";
import { formatBytes, timeAgo } from "../lib";
import type { Asset } from "../types";

interface DeleteResult {
  deleted: string[];
  skipped: { id: string; name?: string; reason: string }[];
  freed_bytes: number;
}

/** Confirmation + request shared by the grid ("Apagar selecionados") and the detail panel. Deleting is permanent: files leave the disk. */
function useDeleteAssets(onDone: (r: DeleteResult) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => api<DeleteResult>("/assets/delete", { method: "POST", json: { asset_ids: ids } }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["asset"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      onDone(r);
    },
  });
}

function confirmDelete(names: string[], t: Translate): boolean {
  const list = names.slice(0, 6).join(", ") + (names.length > 6 ? t(" e mais {0}", names.length - 6) : "");
  return window.confirm(
    t("Apagar {0} ({1})?\n\nTodas as versões e arquivos (GLB, FBX, BLEND, texturas e ZIP) saem do disco. Isso não pode ser desfeito.", names.length === 1 ? t("este modelo") : t("{0} modelos", names.length), list),
  );
}

function deleteMessage(r: DeleteResult, t: Translate): string {
  const parts = [];
  if (r.deleted.length) parts.push(t("{0} apagado(s), {1} liberados", r.deleted.length, formatBytes(r.freed_bytes)));
  if (r.skipped.length) parts.push(t("{0} não apagado(s): {1}", r.skipped.length, r.skipped.map((x) => `${x.name ?? x.id} (${x.reason})`).join("; ")));
  return parts.join(" · ");
}

const REVIEW: Record<string, string> = { pending: "Pendente", approved: "Aprovado", rejected: "Rejeitado" };

export function Library() {
  const { language, t } = useLocale();
  const { assetId } = useParams();
  const [queryParams] = useSearchParams();
  const requestedVersion = Number(queryParams.get("version"));
  const initialVersion = Number.isSafeInteger(requestedVersion) && requestedVersion > 0 ? requestedVersion : undefined;
  const nav = useNavigate();
  const [view, setView] = useState<"grid" | "list">("grid");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [review, setReview] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [experimentsOnly, setExperimentsOnly] = useState(false);
  const [sort, setSort] = useState("-created_at");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState<string | null>(null);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ username: string; role: string }>("/auth/me") });
  const canDelete = me.data?.role === "admin" || me.data?.role === "operator";
  const del = useDeleteAssets((r) => {
    setNotice(deleteMessage(r, t));
    setSelected(new Set());
    if (assetId && r.deleted.includes(assetId)) nav("/library");
  });
  const query = `/assets?limit=200&sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ""}${category ? `&category=${category}` : ""}${review ? `&review_status=${review}` : ""}${favOnly ? "&favorite=true" : ""}${experimentsOnly ? "&tag=city-experimentos" : ""}`;
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
    if (!res.ok) return alert(t("Falha no download: {0}", res.status));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = "assetforge_assets.zip";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const deleteSelected = () => {
    const names = items.filter((a) => selected.has(a.id)).map((a) => a.name);
    if (names.length && confirmDelete(names, t)) del.mutate([...selected]);
  };
  const allVisible = items.length > 0 && items.every((a) => selected.has(a.id));
  return (
    <div className={`lib-layout ${assetId ? "" : "no-detail"}`}>
      <div className="grid" style={{ gap: 12, minWidth: 0 }}>
        <div className="row wrap">
          <input style={{ width: 240 }} placeholder={t("Buscar por nome, id, categoria…")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Buscar assets")} />
          <select style={{ width: 170 }} value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t("Categoria")}>
            <option value="">{t("todas as categorias")}</option>
            {Object.entries(list.data?.facets.category ?? {}).map(([c, n]) => (
              <option key={c} value={c}>
                {c} ({n})
              </option>
            ))}
          </select>
          <select style={{ width: 140 }} value={review} onChange={(e) => setReview(e.target.value)} aria-label={t("Revisão")}>
            <option value="">{t("qualquer revisão")}</option>
            {Object.entries(REVIEW).map(([k, v]) => (
              <option key={k} value={k}>
                {t(v)}
              </option>
            ))}
          </select>
          <select style={{ width: 150 }} value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Ordenar")}>
            <option value="-created_at">{t("mais recentes")}</option>
            <option value="name">{t("nome")}</option>
            <option value="-triangle_count">{t("mais triângulos")}</option>
            <option value="triangle_count">{t("menos triângulos")}</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={favOnly} onChange={(e) => setFavOnly(e.target.checked)} /> {t("favoritos")}
          </label>
          <label className="check">
            <input type="checkbox" checked={experimentsOnly} onChange={(e) => setExperimentsOnly(e.target.checked)} /> {t("Experimentos CITY+++")}
          </label>
          <div className="spacer" />
          <span className="muted">{list.data?.total ?? 0} assets</span>
          <button className="icon" onClick={() => setView(view === "grid" ? "list" : "grid")} aria-label={t("Alternar grade/lista")} title={t("Alternar grade/lista")}>
            {view === "grid" ? <List size={15} /> : <Grid3x3 size={15} />}
          </button>
          <button disabled={!items.length} onClick={() => setSelected(allVisible ? new Set() : new Set(items.map((a) => a.id)))}>
            {allVisible ? t("Limpar seleção") : t("Selecionar todos")}
          </button>
          <button disabled={!selected.size} onClick={downloadZip}>
            <Package size={14} />{" "}{t("Baixar")}{" "}{selected.size || ""} (ZIP)
          </button>
          {canDelete && (
            <button className="danger" disabled={!selected.size || del.isPending} onClick={deleteSelected} title={t("Apaga do disco os modelos selecionados")}>
              <Trash2 size={14} /> {del.isPending ? t("Apagando…") : t("Apagar {0}", selected.size || "")}
            </button>
          )}
        </div>
        {notice && (
          <div className="note" role="status">
            {notice} <button className="icon ghost" onClick={() => setNotice(null)} aria-label={t("Fechar aviso")}><X size={12} /></button>
          </div>
        )}
        <ErrorNote error={del.error} />
        {items.length === 0 ? (
          <Empty>{list.isLoading ? t("Carregando…") : t("Nenhum asset encontrado.")}</Empty>
        ) : view === "grid" ? (
          <div className="cards">
            {items.map((a) => (
              <div key={a.id} className={`card ${assetId === a.id ? "selected" : ""}`} onClick={() => nav(`/library/${a.id}`)}>
                <Thumb assetId={a.id} alt={a.name} hasThumb={a.has_thumbnail} />
                <div className="corner">
                  {a.favorite && <span className="chip">♥</span>}
                  {a.review_status !== "pending" && <span className={`chip ${a.review_status === "approved" ? "check-ok" : "check-fail"}`}>{t(REVIEW[a.review_status] ?? a.review_status)}</span>}
                </div>
                <input className="check-box" type="checkbox" checked={selected.has(a.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(a.id)} aria-label={t("Selecionar {0}", a.name)} />
                <div className="meta">
                  <div className="title">{a.name}</div>
                  <div className="sub">
                    <span>{a.category}</span>
                    <span>{a.triangle_count.toLocaleString(language)} △</span>
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
                    <th>{t("Nome")}</th>
                    <th>{t("Categoria")}</th>
                    <th>{t("Triângulos")}</th>
                    <th>{t("Dimensões (m)")}</th>
                    <th>{t("Versão")}</th>
                    <th>{t("Revisão")}</th>
                    <th>{t("Criado")}</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => (
                    <tr key={a.id} className={`clickable ${assetId === a.id ? "selected" : ""}`} onClick={() => nav(`/library/${a.id}`)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggle(a.id)} aria-label={t("Selecionar {0}", a.name)} />
                      </td>
                      <td>
                        {a.favorite ? "♥ " : ""}
                        {a.name}
                        <div className="muted mono">{a.id}</div>
                      </td>
                      <td>{a.category}</td>
                      <td className="mono">{a.triangle_count.toLocaleString(language)}</td>
                      <td className="mono">{a.dimensions_m?.map((d) => d.toFixed(1)).join(" × ") ?? "—"}</td>
                      <td>v{a.current_version}</td>
                      <td>{t(REVIEW[a.review_status] ?? a.review_status)}</td>
                      <td className="muted">{timeAgo(a.created_at, undefined, t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
      {assetId && <AssetDetail key={`${assetId}:${initialVersion ?? ""}`} id={assetId} initialVersion={initialVersion} onClose={() => nav("/library")} />}
    </div>
  );
}

function AssetDetail({ id, initialVersion, onClose }: { id: string; initialVersion?: number; onClose: () => void }) {
  const { language, t } = useLocale();
  const qc = useQueryClient();
  const token = useDownloadToken();
  const [version, setVersion] = useState(initialVersion);
  const [detailQuery] = useSearchParams();
  const [tab, setTab] = useState<"preview" | "compare" | "info" | "validation" | "versions" | "files">(
    detailQuery.get("tab") === "compare" ? "compare" : "preview",
  );
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
  const nav = useNavigate();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ username: string; role: string }>("/auth/me") });
  const canDelete = me.data?.role === "admin" || me.data?.role === "operator";
  const del = useDeleteAssets((r) => {
    if (r.deleted.includes(id)) {
      nav("/library");
      return;
    }
    window.alert(deleteMessage(r, t));
  });
  const regen = useMutation({
    mutationFn: async () => {
      if (!a?.manifest) throw new Error(t("sem manifesto"));
      const seedText = window.prompt(t("Seed para a nova versão (vazio = mesma seed)"), String(a.seed ?? ""));
      if (seedText === null) return null;
      const { summary: _s, ...params } = a.manifest.generation_params as Record<string, unknown>;
      void _s;
      if (seedText.trim()) params.seed = Number(seedText);
      const formats = [...new Set((a.files ?? []).filter((f) => ["glb", "blend", "fbx"].includes(f.format) && f.role !== "texture").map((f) => f.format))];
      return api("/jobs", { method: "POST", json: { name: a.name, asset_id: a.id, params, quality_profile: a.manifest.quality_profile, formats } });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
  if (asset.error instanceof ApiError && asset.error.status === 404) return <Panel title="Asset"><Empty>{t("Asset não encontrado.")}</Empty></Panel>;
  if (!a) return <Panel title="Asset"><Empty>{t("Carregando…")}</Empty></Panel>;
  const m = a.manifest;
  const archive = m?.generation_params.archive as { worker: string; requested_resolution: number; effective_resolution: number | null; wall_seconds: number } | undefined;
  const ver = a.version_info?.version ?? a.current_version;
  const lodFile = m?.lods?.[lod]?.file ?? "model.glb";
  const glb = token ? fileUrl(a.id, lodFile, token, ver) : null;
  const over = m?.triangle_budget && stats ? stats.triangles > m.triangle_budget[1] : false;
  return (
    <Panel
      title={
        <span>
          {a.name} <span className="muted mono">v{ver}{m?.generator_id === "asset.prepare" ? t(" · Derivado") : m?.generator_id === "experimental.reconstruct" ? " · Master" : ""}</span>
        </span>
      }
      actions={
        <span className="row" style={{ gap: 4 }}>
          {canDelete && (
            <button className="icon ghost danger" disabled={del.isPending} onClick={() => confirmDelete([a.name], t) && del.mutate([a.id])} aria-label={t("Apagar este modelo")} title={t("Apagar este modelo (remove os arquivos do disco)")}>
              <Trash2 size={15} />
            </button>
          )}
          <button className="icon ghost" onClick={onClose} aria-label={t("Fechar detalhe")}>
            <X size={15} />
          </button>
        </span>
      }
    >
      <div className="tabs" role="tablist">
        {(
          [
            ["preview", t("Preview 3D")],
            ["compare", t("Comparar")],
            ["info", t("Geometria e materiais")],
            ["validation", t("Validação")],
            ["versions", t("Versões")],
            ["files", t("Arquivos")],
          ] as const
        ).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {t(l)}
          </button>
        ))}
      </div>
      {tab === "compare" && (m?.generator_id === "asset.prepare" && a.files?.some((file) => file.name === "quality.json")
        ? <OptimizationComparison key={`${id}-${ver}`} asset={a} version={ver} token={token} />
        : <AssetComparison key={`${id}-${ver}`} asset={a} version={ver} token={token} />)}
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
              <input type="checkbox" checked={rotate} onChange={(e) => setRotate(e.target.checked)} /> {t("Girar")}
            </label>
            {(m?.lods?.length ?? 0) > 1 && (
              <label className="check">
                LOD
                <select style={{ width: 150 }} value={lod} onChange={(e) => setLod(Number(e.target.value))} aria-label={t("Nível de detalhe")}>
                  {m!.lods.map((x, i) => (
                    <option key={i} value={i}>
                      LOD{x.level} · {x.triangles.toLocaleString(language)} △
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {stats && (
            <div className="row wrap muted" style={{ marginTop: 6, fontSize: 12 }}>
              <span className={over ? "check-warn" : ""}>{stats.triangles.toLocaleString(language)}{" "}{t("triângulos")}{" "}{m?.triangle_budget ? t("(orçamento {0})", m.triangle_budget.join("–")) : ""}</span>
              <span>· {stats.size.map((s) => s.toFixed(1)).join(" × ")} {m?.generator_id === "experimental.reconstruct" ? "u." : "m"}</span>
              <span>· {stats.meshes}{" "}{t("malhas/materiais")}</span>
            </div>
          )}
        </>
      )}
      {tab === "info" && m && (
        <div className="grid" style={{ gap: 12 }}>
          <dl className="kv">
            <dt>{t("Categoria")}</dt>
            <dd>{a.category}</dd>
            <dt>{t("Dimensões")}</dt>
            <dd>{a.dimensions_m?.map((d) => d.toFixed(2)).join(" × ")} {m.generator_id === "experimental.reconstruct" ? t("unidades do motor") : "m"}{" "}{t("(L×A×P)")}</dd>
            <dt>{t("Pivô")}</dt>
            <dd>{m.generator_id === "experimental.reconstruct" ? t("Sistema de coordenadas original do motor") : t("Centro da base (Y-up)")}</dd>
            {m.provenance.weights_revision && <>
              <dt>{t("Pesos")}</dt><dd className="mono">{m.provenance.weights} @ {m.provenance.weights_revision}</dd>
            </>}
            {m.provenance.master_sha256 && <><dt>{t("SHA-256 do master")}</dt><dd className="mono">{m.provenance.master_sha256}</dd></>}
            {m.provenance.source_version && <><dt>{t("Origem do derivado")}</dt><dd>Master v{m.provenance.source_version}</dd></>}
            {archive && <>
              <dt>{t("Worker original")}</dt><dd>{archive.worker === "4090" ? "RTX 4090" : "DGX Spark"}</dd>
              <dt>{t("Resolução")}</dt><dd>{archive.requested_resolution}{" "}{t("solicitada ·")}{" "}{archive.effective_resolution ?? "—"}{" "}{t("efetiva")}</dd>
              <dt>{t("Tempo de geração")}</dt><dd>{archive.wall_seconds.toLocaleString(language)} s</dd>
            </>}
            <dt>{t("Triângulos")}</dt>
            <dd>
              {m.triangle_count.toLocaleString(language)} (LOD0){m.triangle_budget && t(" · orçamento {0}", m.triangle_budget.join("–"))}
            </dd>
            <dt>{t("Gerador")}</dt>
            <dd className="mono">
              {m.generator_id}@{m.generator_version} · seed {a.seed}
            </dd>
            <dt>{t("Motor de export")}</dt>
            <dd>{a.engine}</dd>
            <dt>{t("Perfil visual")}</dt>
            <dd>{a.art_profile}</dd>
            <dt>{t("Licença")}</dt>
            <dd>{t(m.license)}</dd>
            <dt>LODs</dt>
            <dd>{m.lods.map((l) => `LOD${l.level}: ${l.triangles}`).join(", ")}{" "}{t("(LODs adicionais: Milestone 3)")}</dd>
            <dt>{t("Colisão")}</dt>
            <dd>{m.colliders.map((c) => `${c.type} ${c.size.map((s) => s.toFixed(1)).join("×")}`).join(", ")}</dd>
            <dt>{t("Pontos de conexão")}</dt>
            <dd>{m.connection_points.map((c) => c.name).join(", ") || "—"}</dd>
          </dl>
          <div>
            <h4 style={{ margin: "0 0 6px" }}>{t("Materiais")}</h4>
            <div className="row wrap">
              {m.materials.map((mt) => (
                <span className="chip" key={mt.name} title={t("{0} · rugosidade {1} · metal {2}", mt.texture ?? t("cor lisa"), mt.roughness, mt.metallic)}>
                  <span className="swatch" style={{ background: mt.base_color }} />
                  {mt.name}
                </span>
              ))}
            </div>
          </div>
          <div>
            <h4 style={{ margin: "0 0 6px" }}>{t("Texturas")}</h4>
            <div className="row wrap">
              {token &&
                m.textures.map((t) => (
                  <a key={t} href={fileUrl(a.id, t, token, ver)} target="_blank" rel="noreferrer" title={t}>
                    <img alt={t} src={fileUrl(a.id, t, token, ver)} width={64} height={64} style={{ borderRadius: 4, border: "1px solid var(--border)" }} />
                  </a>
                ))}
            </div>
          </div>
          <p className="note">{t("Edição de escala, rotação, pivô, materiais e geometria (Asset Inspector) chega no Milestone 3; operações destrutivas criarão novas versões.")}</p>
        </div>
      )}
      {tab === "validation" && a.validation && (
        <div className="grid" style={{ gap: 6 }}>
          <div className={a.validation.passed ? "check-ok" : "check-fail"}>{a.validation.passed ? t("✔ Validação aprovada") : t("✘ Validação reprovada")}</div>
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
              <th>{t("Versão")}</th>
              <th>{t("Triângulos")}</th>
              <th>{t("Motor")}</th>
              <th>{t("Criada")}</th>
            </tr>
          </thead>
          <tbody>
            {(a.versions ?? []).slice().reverse().map((v) => (
              <tr key={v.version} className="clickable" onClick={() => setVersion(v.version)}>
                <td>
                  v{v.version} {v.version === a.current_version && <span className="chip">{t("atual")}</span>} {v.version === ver && <span className="chip">{t("vendo")}</span>}
                </td>
                <td className="mono">{v.triangle_count.toLocaleString(language)}</td>
                <td>{v.engine}</td>
                <td className="muted">{timeAgo(v.created_at, undefined, t)}</td>
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
          <Check size={14} /> {t("Aprovar")}
        </button>
        <button className={a.review_status === "rejected" ? "danger" : ""} onClick={() => patch.mutate({ review_status: a.review_status === "rejected" ? "pending" : "rejected" })}>
          <X size={14} /> {t("Rejeitar")}
        </button>
        <button onClick={() => patch.mutate({ favorite: !a.favorite })} aria-pressed={a.favorite}>
          <Heart size={14} fill={a.favorite ? "currentColor" : "none"} /> {t("Favorito")}
        </button>
        {m?.generator_id === "experimental.reconstruct" ? <Link className="btn"
          to={`/engines?${new URLSearchParams({ asset: a.id, version: String(ver) })}`}>
          <RefreshCw size={14} /> {t("Repetir geração")}
        </Link> : m?.generator_id !== "asset.prepare" && <button onClick={() => regen.mutate()} disabled={regen.isPending}>
          <RefreshCw size={14} /> {t("Nova versão")}
        </button>}
        {m && m.generator_id !== "asset.prepare" && ["building", "vehicle", "npc", "prop"].includes(a.category) &&
          <Link className="btn" to={`/prepare?${new URLSearchParams({ asset: a.id, version: String(ver) })}`}>{t("Preparar para Unity")}</Link>}
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
          <Package size={14} /> {t("Pacote ZIP")}
        </a>
      </div>
      <div className="row wrap" style={{ marginTop: 10 }}>
        {a.tags.map((tag) => (
          <span key={tag} className="chip">
            #{tag}{" "}
            <button className="ghost icon" style={{ padding: 0, border: 0 }} aria-label={t("Remover tag {0}", tag)} onClick={() => patch.mutate({ tags: a.tags.filter((x) => x !== tag) })}>
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
