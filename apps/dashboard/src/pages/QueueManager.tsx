import { portuguese, useLocale, type Translate } from "../i18n";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, RotateCcw, X, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorNote, Progress, StatusBadge, Thumb } from "../components/ui";
import { formatDuration, stageLabel, timeAgo } from "../lib";
import type { Job, JobLog, Worker } from "../types";

const FILTERS: [string, string][] = [
  ["", "Todos"],
  ["running", "Executando"],
  ["queued", "Na fila"],
  ["succeeded", "Concluídos"],
  ["failed", "Falhas"],
  ["cancelled", "Cancelados"],
];

const KIND: Record<string, string> = { "experimental.reconstruct": "Reconstrução 3D", "ai.image_to_3d": "Imagem → 3D", "ai.text_to_3d": "Texto → 3D", "procedural.building": "Procedural" };

/** Short, readable message for the most common failures; the full text stays in the tooltip and in the job detail. */
export function friendlyError(e: string | null, t: Translate = portuguese): string {
  if (!e) return t("Falhou (veja os detalhes)");
  if (e.includes("output validation failed")) return t("O modelo gerado não passou na validação automática");
  if (e.includes("timeout")) return t("Demorou mais que o limite");
  return e.length > 90 ? `${e.slice(0, 90)}…` : e;
}

export function QueueManager() {
  const { t } = useLocale();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const batch = params.get("batch") ?? "";
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const jobs = useQuery({
    queryKey: ["jobs", status, batch, q],
    queryFn: () => api<{ total: number; items: Job[] }>(`/jobs?limit=200${status ? `&status=${status}` : ""}${batch ? `&batch_id=${batch}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    refetchInterval: 3000,
  });
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers") });
  const wname = (id: string | null) => workers.data?.find((w) => w.id === id)?.name ?? (id ? id.slice(0, 8) : "—");
  const inv = () => qc.invalidateQueries({ queryKey: ["jobs"] });
  const cancel = useMutation({ mutationFn: (id: string) => api(`/jobs/${id}/cancel`, { method: "POST" }), onSuccess: inv });
  const retry = useMutation({ mutationFn: (id: string) => api(`/jobs/${id}/retry`, { method: "POST" }), onSuccess: inv });
  const patch = useMutation({ mutationFn: ({ id, ...b }: { id: string; priority?: number; clear_schedule?: boolean }) => api(`/jobs/${id}`, { method: "PATCH", json: b }), onSuccess: inv });
  const items = jobs.data?.items ?? [];
  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="row wrap">
        {FILTERS.map(([v, l]) => (
          <button key={v} className={status === v ? "primary" : ""} onClick={() => setStatus(v)}>
            {t(l)}
          </button>
        ))}
        <input style={{ width: 220 }} placeholder={t("Buscar por nome…")} value={q} onChange={(e) => setQ(e.target.value)} />
        {batch && (
          <span className="chip">
            {t("lote")} {batch} <Link to="/queue">✕</Link>
          </span>
        )}
        <div className="spacer" />
        <span className="muted">{jobs.data?.total ?? 0} jobs</span>
      </div>
      <ErrorNote error={cancel.error ?? retry.error ?? patch.error} />
      <div className="q-list">
        {items.length === 0 ? (
          <Empty>{t("Nenhum pedido neste filtro.")}</Empty>
        ) : (
          items.map((j) => (
            <div key={j.id} className={`q-item st-${j.status}`} onClick={() => setOpen(j.id)}>
              <div className="q-thumb">{j.status === "succeeded" ? <Thumb assetId={j.asset_id} alt={j.name} /> : <span className={j.status === "running" ? "spin" : "q-dot"} />}</div>
              <div className="q-main">
                <div className="q-title">
                  {j.name} <span className="chip">{t(KIND[j.job_type] ?? j.job_type)}</span>
                </div>
                {j.status === "running" || j.status === "queued" ? (
                  <>
                    <div className="st-bar"><i style={{ width: `${Math.max(2, j.progress * 100)}%` }} /></div>
                    <div className="muted q-sub">{j.status === "queued" ? t("Aguardando um worker livre") : `${Math.round(j.progress * 100)}% · ${stageLabel(j.current_stage, t)}`}{j.eta_seconds ? ` · ~${formatDuration(j.eta_seconds)}` : ""}</div>
                  </>
                ) : j.status === "failed" ? (
                  <div className="check-fail q-sub" title={j.error ?? ""}>{friendlyError(j.error, t)}</div>
                ) : (
                  <div className="muted q-sub">{j.status === "cancelled" ? t("Cancelado") : t("Concluído")} · {timeAgo(j.finished_at ?? j.created_at, undefined, t)}</div>
                )}
              </div>
              <div className="q-actions" onClick={(e) => e.stopPropagation()}>
                <StatusBadge state={j.state} />
                {j.status === "queued" && (
                  <>
                    <button className="icon" title={t("Aumentar prioridade")} onClick={() => patch.mutate({ id: j.id, priority: Math.min(100, j.priority + 1) })}><ArrowUp size={13} /></button>
                    <button className="icon" title={t("Diminuir prioridade")} onClick={() => patch.mutate({ id: j.id, priority: Math.max(-100, j.priority - 1) })}><ArrowDown size={13} /></button>
                  </>
                )}
                {(j.status === "queued" || j.status === "running") && !j.cancel_requested && (
                  <button className="icon danger" title={t("Cancelar")} onClick={() => cancel.mutate(j.id)}><XCircle size={14} /></button>
                )}
                {(j.status === "failed" || j.status === "cancelled") && (
                  <button title={t("Tentar de novo (cria um novo pedido)")} onClick={() => retry.mutate(j.id)}><RotateCcw size={14} />{" "}{t("Tentar de novo")}</button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
      {open && <JobDrawer id={open} onClose={() => setOpen(null)} wname={wname} />}
    </div>
  );
}

function JobDrawer({ id, onClose, wname }: { id: string; onClose: () => void; wname: (id: string | null) => string }) {
  const { language, t } = useLocale();
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api<Job>(`/jobs/${id}`), refetchInterval: 2000 });
  const logs = useQuery({ queryKey: ["job", id, "logs"], queryFn: () => api<{ items: JobLog[] }>(`/jobs/${id}/logs?limit=1000`), refetchInterval: 2000 });
  const j = job.data;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label={t("Detalhe do job")}>
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ fontSize: 16 }}>{j?.name ?? id}</h2>
          <div className="spacer" />
          <button className="icon ghost" onClick={onClose} aria-label={t("Fechar")}>
            <X size={16} />
          </button>
        </div>
        {j && (
          <>
            <div className="row wrap" style={{ marginBottom: 10 }}>
              <StatusBadge state={j.state} />
              <span className="mono muted">{j.id}</span>
              {j.job_type === "experimental.reconstruct" && (
                <Link to={`/engines?job=${encodeURIComponent(j.id)}`} className="btn">{t("Abrir no estúdio")}</Link>
              )}
              {j.status === "succeeded" && (
                <Link to={`/library/${j.asset_id}`} className="btn">
                  {t("Abrir asset v")}{j.asset_version}
                </Link>
              )}
            </div>
            <Progress value={j.progress} tone={j.status === "succeeded" ? "ok" : ""} />
            {j.error && <div className="error-note">{j.error}</div>}
            <h3 style={{ margin: "14px 0 6px" }}>{t("Etapas")}</h3>
            <div className="stage-list">
              {(j.plan ?? []).map((p) => {
                const st = j.stages?.[p.name];
                return (
                  <div className="stage" key={p.name}>
                    <span className={`dot ${st?.status === "done" ? "ok" : st?.status === "failed" ? "err" : st?.status === "running" ? "warn" : ""}`} />
                    <span style={{ width: 170 }}>{stageLabel(p.name, t)}</span>
                    <span className="muted">{st?.status === "done" ? t("concluída") : st?.status === "running" ? t("em andamento") : st?.status === "failed" ? "falhou" : "pendente"}</span>
                    {st?.detail && <span className="muted mono">{st.detail}</span>}
                  </div>
                );
              })}
              {!(j.plan ?? []).length && <span className="muted">{t("O worker ainda não reportou etapas.")}</span>}
            </div>
            <h3 style={{ margin: "14px 0 6px" }}>{t("Tentativas")}</h3>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Worker</th>
                  <th>{t("Início")}</th>
                  <th>{t("Resultado")}</th>
                </tr>
              </thead>
              <tbody>
                {(j.attempt_history ?? []).map((a) => (
                  <tr key={a.attempt}>
                    <td>{a.attempt}</td>
                    <td>{wname(a.worker_id)}</td>
                    <td className="muted">{timeAgo(a.started_at, undefined, t)}</td>
                    <td>
                      <span className={`badge st-${a.outcome === "succeeded" ? "succeeded" : a.outcome === "running" ? "running" : "failed"}`}>{a.outcome}</span>
                      {a.error && <div className="muted" style={{ fontSize: 11 }}>{a.error.slice(0, 120)}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 style={{ margin: "14px 0 6px" }}>Logs</h3>
            <div className="logbox" role="log">
              {(logs.data?.items ?? []).map((l) => (
                <div key={l.id} className={l.source === "server" ? "l-server" : `l-${l.level}`}>
                  {new Date(l.ts).toLocaleTimeString(language)} [{l.source === "server" ? t("servidor") : `t${l.attempt}`}] {l.message}
                </div>
              ))}
              {!logs.data?.items.length && <span className="muted">{t("sem logs")}</span>}
            </div>
            <h3 style={{ margin: "14px 0 6px" }}>{t("Parâmetros")}</h3>
            <pre className="logbox">{JSON.stringify(j.params, null, 2)}</pre>
          </>
        )}
      </aside>
    </>
  );
}
