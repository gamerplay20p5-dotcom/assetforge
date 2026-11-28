import { useLocale } from "../i18n";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Settings2, Wrench } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorNote, Meter, Panel } from "../components/ui";
import { formatBytes, stateLabel, timeAgo } from "../lib";
import type { Worker } from "../types";

const STATE_LABEL: Record<string, string> = { enabled: "Habilitado", disabled: "Desabilitado", maintenance: "Manutenção" };
const STATUS_DOT: Record<string, string> = { idle: "ok", busy: "warn", offline: "err", disabled: "", maintenance: "warn" };

export function WorkersManager() {
  const { language, t } = useLocale();
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
        <span className="muted">{list.filter((w) => w.online).length}{" "}{t("online de")}{" "}{list.length}</span>
        <div className="spacer" />
        <button onClick={() => create.mutate()}>
          <Plus size={14} /> {t("Novo token de registro")}
        </button>
      </div>
      <ErrorNote error={create.error ?? patch.error} />
      {enr && (
        <div className="note">
          <strong>{t("Token de registro (exibido uma única vez, válido até")}{" "}{new Date(enr.expires_at).toLocaleString(language)}):</strong>
          <pre className="logbox" style={{ margin: "6px 0" }}>{enr.token}</pre>
          {t("No servidor do worker, defina")} <span className="mono">ASSETFORGE_ENROLLMENT_TOKEN</span>{" "}{t("e")}{" "}<span className="mono">ASSETFORGE_SERVER_URL</span> {t("no .env do Compose (veja docs/DEPLOYMENT.md).")}
        </div>
      )}
      {list.length === 0 ? (
        <Panel>
          <Empty>{t("Nenhum worker registrado. Gere um token de registro e suba um worker (docs/DEPLOYMENT.md).")}</Empty>
        </Panel>
      ) : (
        <Panel>
          <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
            <table>
              <thead>
                <tr>
                  <th>Node</th>
                  <th>{t("Tipo")}</th>
                  <th>Status</th>
                  <th>{t("Endereço")}</th>
                  <th>Heartbeat</th>
                  <th>{t("Hardware detectado")}</th>
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
                        <div className="muted" style={{ fontSize: 11 }}>{t(STATE_LABEL[w.state] ?? w.state)}</div>
                      </td>
                      <td className="mono">{w.address}</td>
                      <td className="muted">{timeAgo(w.last_heartbeat, undefined, t)}</td>
                      <td style={{ fontSize: 12 }}>
                        {w.capabilities.cpu_cores_total} threads · {formatBytes((w.capabilities.ram_total_mb ?? 0) * 1024 * 1024)}
                        <div className="muted">{gpu ? `${gpu.name}${gpu.vram_total_mb ? ` · ${gpu.vram_total_mb} MB` : t(" · VRAM não medida")}` : t("sem GPU declarada")}</div>
                      </td>
                      <td>
                        {w.active_jobs} {t("ativos")}
                        <div className="muted" style={{ fontSize: 11 }}>✓{w.jobs_succeeded} ✗{w.jobs_failed}</div>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="row">
                          {w.state !== "enabled" && <button onClick={() => patch.mutate({ id: w.id, state: "enabled" })}>{t("Habilitar")}</button>}
                          {w.state === "enabled" && <button onClick={() => patch.mutate({ id: w.id, state: "disabled" })}>{t("Desabilitar")}</button>}
                          {w.state !== "maintenance" && (
                            <button className="icon" title={t("Modo manutenção (termina jobs atuais, não recebe novos)")} onClick={() => patch.mutate({ id: w.id, state: "maintenance" })}>
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
  const { t } = useLocale();
  const [jobs, setJobs] = useState(String(w.limits.max_concurrent_jobs ?? 1));
  const [cpu, setCpu] = useState(String(w.limits.cpu_cores ?? ""));
  const [ram, setRam] = useState(String(w.limits.ram_mb ?? ""));
  const detail = useQuery({ queryKey: ["workers", w.id], queryFn: () => api<Worker>(`/workers/${w.id}`), refetchInterval: 5000 });
  const telemetry = w.telemetry;
  const caps = w.capabilities;
  const adaptive = w.kind === "nvidia";
  const engineGpu = telemetry.engine_gpu;
  return (
    <div className="grid g3">
      <Panel title={t("Telemetria ao vivo")}>
        <Meter label="CPU" value={telemetry.cpu_percent ?? null} />
        <Meter label="RAM" value={telemetry.ram_used_mb ?? null} max={telemetry.ram_total_mb} unit="MB" />
        {(telemetry.gpus ?? []).map((g, i) => (
          <div key={i}>
            <Meter label={`GPU ${g.name}`} value={g.utilization_percent ?? null} na={t("utilização não exposta")} />
            <Meter label="VRAM" value={g.vram_used_mb ?? null} max={g.vram_total_mb} unit="MB" na={t("não medida")} />
          </div>
        ))}
        {adaptive && engineGpu ? <>
          <Meter label={engineGpu.name ?? "GPU NVIDIA"} value={engineGpu.utilization_percent ?? null} />
          {engineGpu.unified
            ? <Meter label={t("RAM unificada livre")} value={engineGpu.ram_available_mb ?? null} max={telemetry.ram_total_mb} unit="MB" />
            : <Meter label={t("VRAM livre")} value={engineGpu.vram_free_mb ?? null} max={engineGpu.vram_total_mb ?? undefined} unit="MB" />}
        </> : !(telemetry.gpus ?? []).length && <Meter label="GPU" value={null} na={t("sem GPU declarada neste node")} />}
        {Object.entries(w.capabilities.cpu3d?.providers ?? {}).map(([n, p]) => {
          const tel = telemetry.cpu3d?.[n];
          return (
            <div key={n} style={{ marginBottom: 10 }}>
              <Meter label={t("Provider {0}{1}", n, p.ready ? "" : t(" — indisponível"))} value={tel?.container_mem_mb ?? null} max={tel?.container_mem_limit_mb ?? undefined} unit="MB" na={p.reason ?? t("sem dados")} />
              <span className="muted" style={{ fontSize: 11 }}>{p.ready ? t("{0} job(s) ativo(s) · {1} threads · concorrência {2}", p.active_jobs ?? 0, p.threads ?? "—", p.concurrency ?? "—") : p.reason}</span>
            </div>
          );
        })}
        {telemetry.gate && <div className="note" style={{ margin: "8px 0" }}>{t("Despacho em espera neste node:")}{" "}{telemetry.gate}</div>}
        <dl className="kv">
          <dt>{t("Temperatura")}</dt>
          <dd>{(engineGpu?.temperature_c ?? telemetry.temperature_c) != null ? `${engineGpu?.temperature_c ?? telemetry.temperature_c} °C` : t("indisponível")}</dd>
        </dl>
      </Panel>
      <Panel title={t("Capacidades")} actions={<Settings2 size={14} />}>
        <dl className="kv">
          <dt>{t("Recursos")}</dt>
          <dd>{caps.features?.join(", ")}</dd>
          <dt>Blender</dt>
          <dd>{caps.blender_version ?? t("não instalado")}</dd>
          <dt>{t("Formatos")}</dt>
          <dd>{caps.formats?.join(", ")}</dd>
          <dt>{t("Runtimes de IA")}</dt>
          <dd>
            OpenVINO: {caps.ai_runtimes?.openvino ?? t("não instalado")} · PyTorch: {caps.ai_runtimes?.torch ?? t("não instalado")}{" "}{t("· validados:")}{" "}{caps.ai_runtimes?.validated?.length ? caps.ai_runtimes.validated.join(", ") : t("nenhum (sem benchmark ainda)")}
          </dd>
          <dt>{t("Janela / cede a")}</dt>
          <dd>
            {caps.schedule?.active_hours || t("sempre")} · CPU host ≤ {caps.schedule?.max_host_cpu_percent || t("sem limite")}% · {caps.schedule?.yield_to?.join(", ") || "—"}
          </dd>
          <dt>{t("Modelos de IA")}</dt>
          <dd>{caps.models?.length ? caps.models.map((m) => m.name).join(", ") : t("nenhum instalado")}</dd>
          <dt>SO / CPU</dt>
          <dd>
            {caps.os} · {caps.cpu_model}
          </dd>
          <dt>{t("Versão do worker")}</dt>
          <dd>{w.version}</dd>
        </dl>
      </Panel>
      <Panel title={t("Limites de recursos (este node também roda outros projetos)")}>
        {adaptive ? <p className="muted">{t("Concorrência adaptativa ·")}{" "}{w.active_jobs}{" "}{t("em execução")}</p> : <>
        <div className="grid g3">
          <label className="field">
            {t("Jobs simultâneos")}
            <input type="number" min={1} value={jobs} onChange={(e) => setJobs(e.target.value)} />
          </label>
          <label className="field">
            {t("Núcleos (reserva)")}
            <input type="number" min={1} value={cpu} onChange={(e) => setCpu(e.target.value)} />
          </label>
          <label className="field">
            RAM (MB)
            <input type="number" min={256} value={ram} onChange={(e) => setRam(e.target.value)} />
          </label>
        </div>
        <button style={{ marginTop: 10 }} onClick={() => onSave({ max_concurrent_jobs: Number(jobs), ...(cpu ? { cpu_cores: Number(cpu) } : {}), ...(ram ? { ram_mb: Number(ram) } : {}) })}>
          {t("Aplicar limites")}
        </button>
        </>}
        <h4 style={{ margin: "14px 0 6px" }}>{t("Histórico recente")}</h4>
        {(detail.data?.recent_jobs ?? []).slice(0, 6).map((j) => (
          <div key={j.id} className="row" style={{ fontSize: 12 }}>
            <span className={`dot ${j.status === "succeeded" ? "ok" : j.status === "failed" ? "err" : "warn"}`} />
            {j.name}
            <span className="muted">{stateLabel(j.status, t)}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}
