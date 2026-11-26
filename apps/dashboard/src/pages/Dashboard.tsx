import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Empty, Meter, Panel, Stat, StatusBadge, Thumb, Progress } from "../components/ui";
import { formatBytes, formatDuration, stageLabel, timeAgo } from "../lib";
import type { Asset, Job, Summary } from "../types";

export function Dashboard() {
  const sum = useQuery({ queryKey: ["summary"], queryFn: () => api<Summary>("/dashboard/summary"), refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: ["jobs", "recent"], queryFn: () => api<{ items: Job[] }>("/jobs?limit=8"), refetchInterval: 5000 });
  const assets = useQuery({ queryKey: ["assets", "recent"], queryFn: () => api<{ items: Asset[] }>("/assets?limit=8&sort=-created_at") });
  const s = sum.data;
  if (!s) return <Empty>Carregando…</Empty>;
  const r = s.resources;
  const maxBar = Math.max(1, ...s.history.map((h) => h.succeeded + h.failed + h.cancelled));
  const usedPct = s.storage.total_bytes ? ((s.storage.total_bytes - s.storage.free_bytes) / s.storage.total_bytes) * 100 : 0;
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="grid g6">
        <Stat label="Assets gerados" value={s.assets.total} hint={`${s.assets.by_review.approved ?? 0} aprovados`} />
        <Stat label="Jobs ativos" value={s.jobs.running} tone="info" />
        <Stat label="Aguardando" value={s.jobs.queued} tone={s.jobs.paused ? "warn" : undefined} hint={s.jobs.paused ? "despacho pausado" : undefined} />
        <Stat label="Concluídos" value={s.jobs.succeeded} tone="ok" />
        <Stat label="Com falha" value={s.jobs.failed} tone={s.jobs.failed ? "err" : undefined} />
        <Stat label="Workers online" value={`${s.workers.online}/${s.workers.total}`} hint={`${s.workers.busy} ocupados`} />
      </div>
      <div className="grid g3">
        <Panel title="Recursos dos workers (medidos)">
          <Meter label="CPU" value={r.cpu_percent} na="nenhum worker online" />
          <Meter label="RAM" value={r.ram_used_mb} max={r.ram_total_mb} unit="MB" na="nenhum worker online" />
          <Meter label="GPU" value={r.gpu_percent} na="sem worker GPU (Milestone 2)" />
          <Meter label="VRAM" value={r.vram_used_mb} max={r.vram_total_mb} unit="MB" na="sem worker GPU (Milestone 2)" />
        </Panel>
        <Panel title="Armazenamento do servidor">
          <Meter label="Disco" value={usedPct} />
          <dl className="kv">
            <dt>Livre</dt>
            <dd>{formatBytes(s.storage.free_bytes)}</dd>
            <dt>Total</dt>
            <dd>{formatBytes(s.storage.total_bytes)}</dd>
            <dt>Assets</dt>
            <dd>{formatBytes(s.storage.assets_bytes)}</dd>
            <dt>Tempo médio/job</dt>
            <dd>{formatDuration(s.avg_job_seconds)}</dd>
          </dl>
        </Panel>
        <Panel title="Histórico de processamento (24 h)">
          <div className="bars" aria-label="Jobs finalizados por hora">
            {s.history.map((h) => {
              const tot = h.succeeded + h.failed + h.cancelled;
              return (
                <div className="col" key={h.hour} title={`${new Date(h.hour).getHours()}h — ${h.succeeded} ok, ${h.failed} falhas, ${h.cancelled} cancelados`}>
                  <div className="seg-ok" style={{ height: `${(h.succeeded / maxBar) * 100}%` }} />
                  <div className="seg-err" style={{ height: `${(h.failed / maxBar) * 100}%` }} />
                  <div className="seg-can" style={{ height: `${(h.cancelled / maxBar) * 100}%` }} />
                  {tot === 0 && <div style={{ height: 2, background: "var(--border)" }} />}
                </div>
              );
            })}
          </div>
          <div className="bar-axis">
            <span>-24h</span>
            <span>
              <span className="check-ok">■</span> ok <span className="check-fail">■</span> falha
            </span>
            <span>agora</span>
          </div>
        </Panel>
      </div>
      <div className="grid g2">
        <Panel title="Jobs recentes" actions={<Link to="/queue">ver fila →</Link>}>
          <div className="panel-body flush table-wrap">
            {jobs.data?.items.length ? (
              <table>
                <tbody>
                  {jobs.data.items.map((j) => (
                    <tr key={j.id}>
                      <td>
                        <div>{j.name}</div>
                        <div className="muted mono">{j.id}</div>
                      </td>
                      <td>
                        <StatusBadge state={j.state} />
                      </td>
                      <td style={{ width: 150 }}>
                        {j.status === "running" ? (
                          <>
                            <Progress value={j.progress} />
                            <div className="muted" style={{ fontSize: 11 }}>{stageLabel(j.current_stage)}</div>
                          </>
                        ) : (
                          <span className="muted">{timeAgo(j.finished_at ?? j.created_at)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty>Nenhum job ainda. Crie o primeiro no Asset Generator.</Empty>
            )}
          </div>
        </Panel>
        <Panel title="Assets recentes" actions={<Link to="/library">biblioteca →</Link>}>
          {assets.data?.items.length ? (
            <div className="cards" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(110px,1fr))" }}>
              {assets.data.items.map((a) => (
                <Link key={a.id} to={`/library/${a.id}`} className="card">
                  <Thumb assetId={a.id} alt={a.name} hasThumb={a.has_thumbnail} />
                  <div className="meta">
                    <div className="title">{a.name}</div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <Empty>Nenhum asset registrado ainda.</Empty>
          )}
        </Panel>
      </div>
    </div>
  );
}
