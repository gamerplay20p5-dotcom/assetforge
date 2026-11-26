import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Clock, RotateCcw, X, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorNote, Panel, Progress, StatusBadge } from "../components/ui";
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

export function QueueManager() {
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
            {l}
          </button>
        ))}
        <input style={{ width: 220 }} placeholder="Buscar por nome…" value={q} onChange={(e) => setQ(e.target.value)} />
        {batch && (
          <span className="chip">
            lote {batch} <Link to="/queue">✕</Link>
          </span>
        )}
        <div className="spacer" />
        <span className="muted">{jobs.data?.total ?? 0} jobs</span>
      </div>
      <ErrorNote error={cancel.error ?? retry.error ?? patch.error} />
      <Panel>
        <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
          {items.length === 0 ? (
            <Empty>Nenhum job neste filtro.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Estado</th>
                  <th style={{ width: 170 }}>Progresso real</th>
                  <th>Worker</th>
                  <th>Tent.</th>
                  <th>Prio</th>
                  <th>ETA</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((j) => (
                  <tr key={j.id} className="clickable" onClick={() => setOpen(j.id)}>
                    <td>
                      <div>{j.name}</div>
                      <div className="muted mono">
                        {j.id} · seed {j.seed ?? "—"}
                      </div>
                    </td>
                    <td>
                      <StatusBadge state={j.state} />
                      {j.not_before && j.state === "scheduled" && (
                        <div className="muted" style={{ fontSize: 11 }}>
                          <Clock size={10} /> {new Date(j.not_before).toLocaleString()}
                        </div>
                      )}
                    </td>
                    <td>
                      <Progress value={j.progress} tone={j.status === "succeeded" ? "ok" : ""} />
                      <div className="muted" style={{ fontSize: 11 }}>
                        {j.status === "running" ? stageLabel(j.current_stage) : j.error ? <span className="check-fail">{j.error.slice(0, 40)}</span> : ""}
                      </div>
                    </td>
                    <td>{wname(j.worker_id)}</td>
                    <td className="mono">
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td className="mono">{j.priority}</td>
                    <td className="mono">{formatDuration(j.eta_seconds)}</td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div className="row">
                        {j.status === "queued" && (
                          <>
                            <button className="icon" title="Aumentar prioridade" onClick={() => patch.mutate({ id: j.id, priority: Math.min(100, j.priority + 1) })}>
                              <ArrowUp size={13} />
                            </button>
                            <button className="icon" title="Diminuir prioridade" onClick={() => patch.mutate({ id: j.id, priority: Math.max(-100, j.priority - 1) })}>
                              <ArrowDown size={13} />
                            </button>
                          </>
                        )}
                        {(j.status === "queued" || j.status === "running") && !j.cancel_requested && (
                          <button className="icon danger" title="Cancelar (cooperativo)" onClick={() => cancel.mutate(j.id)}>
                            <XCircle size={14} />
                          </button>
                        )}
                        {(j.status === "failed" || j.status === "cancelled" || j.status === "succeeded") && (
                          <button className="icon" title="Reprocessar (novo job)" onClick={() => retry.mutate(j.id)}>
                            <RotateCcw size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>
      {open && <JobDrawer id={open} onClose={() => setOpen(null)} wname={wname} />}
    </div>
  );
}

function JobDrawer({ id, onClose, wname }: { id: string; onClose: () => void; wname: (id: string | null) => string }) {
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api<Job>(`/jobs/${id}`), refetchInterval: 2000 });
  const logs = useQuery({ queryKey: ["job", id, "logs"], queryFn: () => api<{ items: JobLog[] }>(`/jobs/${id}/logs?limit=1000`), refetchInterval: 2000 });
  const j = job.data;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label="Detalhe do job">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ fontSize: 16 }}>{j?.name ?? id}</h2>
          <div className="spacer" />
          <button className="icon ghost" onClick={onClose} aria-label="Fechar">
            <X size={16} />
          </button>
        </div>
        {j && (
          <>
            <div className="row wrap" style={{ marginBottom: 10 }}>
              <StatusBadge state={j.state} />
              <span className="mono muted">{j.id}</span>
              {j.status === "succeeded" && (
                <Link to={`/library/${j.asset_id}`} className="btn">
                  Abrir asset v{j.asset_version}
                </Link>
              )}
            </div>
            <Progress value={j.progress} tone={j.status === "succeeded" ? "ok" : ""} />
            {j.error && <div className="error-note">{j.error}</div>}
            <h3 style={{ margin: "14px 0 6px" }}>Etapas</h3>
            <div className="stage-list">
              {(j.plan ?? []).map((p) => {
                const st = j.stages?.[p.name];
                return (
                  <div className="stage" key={p.name}>
                    <span className={`dot ${st?.status === "done" ? "ok" : st?.status === "failed" ? "err" : st?.status === "running" ? "warn" : ""}`} />
                    <span style={{ width: 170 }}>{stageLabel(p.name)}</span>
                    <span className="muted">{st?.status === "done" ? "concluída" : st?.status === "running" ? "em andamento" : st?.status === "failed" ? "falhou" : "pendente"}</span>
                    {st?.detail && <span className="muted mono">{st.detail}</span>}
                  </div>
                );
              })}
              {!(j.plan ?? []).length && <span className="muted">O worker ainda não reportou etapas.</span>}
            </div>
            <h3 style={{ margin: "14px 0 6px" }}>Tentativas</h3>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Worker</th>
                  <th>Início</th>
                  <th>Resultado</th>
                </tr>
              </thead>
              <tbody>
                {(j.attempt_history ?? []).map((a) => (
                  <tr key={a.attempt}>
                    <td>{a.attempt}</td>
                    <td>{wname(a.worker_id)}</td>
                    <td className="muted">{timeAgo(a.started_at)}</td>
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
                  {new Date(l.ts).toLocaleTimeString()} [{l.source === "server" ? "servidor" : `t${l.attempt}`}] {l.message}
                </div>
              ))}
              {!logs.data?.items.length && <span className="muted">sem logs</span>}
            </div>
            <h3 style={{ margin: "14px 0 6px" }}>Parâmetros</h3>
            <pre className="logbox">{JSON.stringify(j.params, null, 2)}</pre>
          </>
        )}
      </aside>
    </>
  );
}
