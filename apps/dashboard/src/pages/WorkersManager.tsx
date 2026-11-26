import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Settings2, Wrench } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorNote, Meter, Panel } from "../components/ui";
import { formatBytes, timeAgo } from "../lib";
import type { Worker } from "../types";

const STATE_LABEL: Record<string, string> = { enabled: "Habilitado", disabled: "Desabilitado", maintenance: "Manutenção" };
const STATUS_DOT: Record<string, string> = { idle: "ok", busy: "warn", offline: "err", disabled: "", maintenance: "warn" };

export function WorkersManager() {
  const qc = useQueryClient();
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 4000 });
  const [open, setOpen] = useState<string | null>(null);
  const [enr, setEnr] = useState<{ token: string; expires_at: string } | null>(null);
  const create = useMutation({
    mutationFn: () => api<{ token: string; expires_at: string }>("/workers/enrollment-tokens", { method: "POST", json: { label: "dashboard", hours: 24 } }),
    onSuccess: setEnr,
  });
  const patch = useMutation({
    mutationFn: ({ id, ...b }: { id: string; state?: string; limits?: Record<string, number> }) => api(`/workers/${id}`, { method: "PATCH", json: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workers"] }),
  });
  const list = workers.data ?? [];
  const sel = list.find((w) => w.id === open);
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="row">
        <span className="muted">{list.filter((w) => w.online).length} online de {list.length}</span>
        <div className="spacer" />
        <button onClick={() => create.mutate()}>
          <Plus size={14} /> Novo token de registro
        </button>
      </div>
      <ErrorNote error={create.error ?? patch.error} />
      {enr && (
        <div className="note">
          <strong>Token de registro (exibido uma única vez, válido até {new Date(enr.expires_at).toLocaleString()}):</strong>
          <pre className="logbox" style={{ margin: "6px 0" }}>{enr.token}</pre>
          No servidor do worker, defina <span className="mono">ASSETFORGE_ENROLLMENT_TOKEN</span> e <span className="mono">ASSETFORGE_SERVER_URL</span> no .env do Compose (veja docs/DEPLOYMENT.md).
        </div>
      )}
      {list.length === 0 ? (
        <Panel>
          <Empty>Nenhum worker registrado. Gere um token de registro e suba um worker (docs/DEPLOYMENT.md).</Empty>
        </Panel>
      ) : (
        <Panel>
          <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
            <table>
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Tipo</th>
                  <th>Status</th>
                  <th>Endereço</th>
                  <th>Heartbeat</th>
                  <th>Hardware detectado</th>
                  <th>Jobs</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((w) => {
                  const gpu = w.capabilities.gpus?.[0];
                  return (
                    <tr key={w.id} className={`clickable ${open === w.id ? "selected" : ""}`} onClick={() => setOpen(w.id)}>
                      <td>
                        <strong>{w.name}</strong>
                        <div className="muted mono">{w.hostname}</div>
                      </td>
                      <td>{w.kind.toUpperCase()}</td>
                      <td>
                        <span className={`dot ${STATUS_DOT[w.status] ?? ""}`} /> {w.online ? w.status : "offline"}
                        <div className="muted" style={{ fontSize: 11 }}>{STATE_LABEL[w.state]}</div>
                      </td>
                      <td className="mono">{w.address}</td>
                      <td className="muted">{timeAgo(w.last_heartbeat)}</td>
                      <td style={{ fontSize: 12 }}>
                        {w.capabilities.cpu_cores_total} threads · {formatBytes((w.capabilities.ram_total_mb ?? 0) * 1024 * 1024)}
                        <div className="muted">{gpu ? `${gpu.name}${gpu.vram_total_mb ? ` · ${gpu.vram_total_mb} MB` : " · VRAM não medida"}` : "sem GPU declarada"}</div>
                      </td>
                      <td>
                        {w.active_jobs} ativos
                        <div className="muted" style={{ fontSize: 11 }}>✓{w.jobs_succeeded} ✗{w.jobs_failed}</div>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="row">
                          {w.state !== "enabled" && <button onClick={() => patch.mutate({ id: w.id, state: "enabled" })}>Habilitar</button>}
                          {w.state === "enabled" && <button onClick={() => patch.mutate({ id: w.id, state: "disabled" })}>Desabilitar</button>}
                          {w.state !== "maintenance" && (
                            <button className="icon" title="Modo manutenção (termina jobs atuais, não recebe novos)" onClick={() => patch.mutate({ id: w.id, state: "maintenance" })}>
                              <Wrench size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
      {sel && <WorkerDetail w={sel} onSave={(limits) => patch.mutate({ id: sel.id, limits })} />}
    </div>
  );
}

function WorkerDetail({ w, onSave }: { w: Worker; onSave: (l: Record<string, number>) => void }) {
  const [jobs, setJobs] = useState(String(w.limits.max_concurrent_jobs ?? 1));
  const [cpu, setCpu] = useState(String(w.limits.cpu_cores ?? ""));
  const [ram, setRam] = useState(String(w.limits.ram_mb ?? ""));
  const detail = useQuery({ queryKey: ["workers", w.id], queryFn: () => api<Worker>(`/workers/${w.id}`), refetchInterval: 5000 });
  const t = w.telemetry;
  const caps = w.capabilities;
  return (
    <div className="grid g3">
      <Panel title="Telemetria ao vivo">
        <Meter label="CPU" value={t.cpu_percent ?? null} />
        <Meter label="RAM" value={t.ram_used_mb ?? null} max={t.ram_total_mb} unit="MB" />
        {(t.gpus ?? []).map((g, i) => (
          <div key={i}>
            <Meter label={`GPU ${g.name}`} value={g.utilization_percent ?? null} na="utilização não exposta" />
            <Meter label="VRAM" value={g.vram_used_mb ?? null} max={g.vram_total_mb} unit="MB" na="não medida" />
          </div>
        ))}
        {!(t.gpus ?? []).length && <Meter label="GPU" value={null} na="sem GPU declarada neste node" />}
        {Object.entries(w.capabilities.cpu3d?.providers ?? {}).map(([n, p]) => {
          const tel = t.cpu3d?.[n];
          return (
            <div key={n} style={{ marginBottom: 10 }}>
              <Meter label={`Provider ${n}${p.ready ? "" : " — indisponível"}`} value={tel?.container_mem_mb ?? null} max={tel?.container_mem_limit_mb ?? undefined} unit="MB" na={p.reason ?? "sem dados"} />
              <span className="muted" style={{ fontSize: 11 }}>{p.ready ? `${p.active_jobs ?? 0} job(s) ativo(s) · ${p.threads} threads · concorrência ${p.concurrency}` : p.reason}</span>
            </div>
          );
        })}
        {t.gate && <div className="note" style={{ margin: "8px 0" }}>Despacho em espera neste node: {t.gate}</div>}
        <dl className="kv">
          <dt>Temperatura</dt>
          <dd>{t.temperature_c != null ? `${t.temperature_c} °C` : "indisponível"}</dd>
        </dl>
      </Panel>
      <Panel title="Capacidades" actions={<Settings2 size={14} />}>
        <dl className="kv">
          <dt>Recursos</dt>
          <dd>{caps.features?.join(", ")}</dd>
          <dt>Blender</dt>
          <dd>{caps.blender_version ?? "não instalado"}</dd>
          <dt>Formatos</dt>
          <dd>{caps.formats?.join(", ")}</dd>
          <dt>Runtimes de IA</dt>
          <dd>
            OpenVINO: {caps.ai_runtimes?.openvino ?? "não instalado"} · PyTorch: {caps.ai_runtimes?.torch ?? "não instalado"} · validados: {caps.ai_runtimes?.validated?.length ? caps.ai_runtimes.validated.join(", ") : "nenhum (sem benchmark ainda)"}
          </dd>
          <dt>Janela / cede a</dt>
          <dd>
            {caps.schedule?.active_hours || "sempre"} · CPU host ≤ {caps.schedule?.max_host_cpu_percent || "sem limite"}% · {caps.schedule?.yield_to?.join(", ") || "—"}
          </dd>
          <dt>Modelos de IA</dt>
          <dd>{caps.models?.length ? caps.models.map((m) => m.name).join(", ") : "nenhum instalado"}</dd>
          <dt>SO / CPU</dt>
          <dd>
            {caps.os} · {caps.cpu_model}
          </dd>
          <dt>Versão do worker</dt>
          <dd>{w.version}</dd>
        </dl>
      </Panel>
      <Panel title="Limites de recursos (este node também roda outros projetos)">
        <div className="grid g3">
          <label className="field">
            Jobs simultâneos
            <input type="number" min={1} value={jobs} onChange={(e) => setJobs(e.target.value)} />
          </label>
          <label className="field">
            Núcleos (reserva)
            <input type="number" min={1} value={cpu} onChange={(e) => setCpu(e.target.value)} />
          </label>
          <label className="field">
            RAM (MB)
            <input type="number" min={256} value={ram} onChange={(e) => setRam(e.target.value)} />
          </label>
        </div>
        <button style={{ marginTop: 10 }} onClick={() => onSave({ max_concurrent_jobs: Number(jobs), ...(cpu ? { cpu_cores: Number(cpu) } : {}), ...(ram ? { ram_mb: Number(ram) } : {}) })}>
          Aplicar limites
        </button>
        <h4 style={{ margin: "14px 0 6px" }}>Histórico recente</h4>
        {(detail.data?.recent_jobs ?? []).slice(0, 6).map((j) => (
          <div key={j.id} className="row" style={{ fontSize: 12 }}>
            <span className={`dot ${j.status === "succeeded" ? "ok" : j.status === "failed" ? "err" : "warn"}`} />
            {j.name}
            <span className="muted">{j.status}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}
