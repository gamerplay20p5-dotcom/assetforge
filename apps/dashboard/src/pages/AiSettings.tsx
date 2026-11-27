import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, KeyRound, Plug, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorNote, Panel, Stat } from "../components/ui";
import { timeAgo } from "../lib";

interface AiKey {
  id: string;
  provider: "gemini" | "grok";
  label: string;
  key_hint: string;
  model: string;
  priority: number;
  enabled: boolean;
  allow_paid: boolean;
  paid: boolean;
  rpm_limit: number;
  rpd_limit: number;
  cooldown_until: string | null;
  last_error: string;
  usage: { rpm: number; rpd: number; tokens_today: number };
}
interface Settings {
  free_only: boolean;
  agent_iterations: number;
  target_score: number;
  data_notice: string;
}
interface ModelRow {
  name: string;
  display: string;
}
interface Req {
  id: number;
  ts: string;
  provider: string;
  model: string;
  task: string;
  job_id: string;
  status: string;
  total_tokens: number;
  latency_ms: number;
  error: string;
}

const PROVIDER_LABEL = { gemini: "Google Gemini", grok: "xAI Grok" } as const;
const STATUS_LABEL: Record<string, string> = { ok: "ok", cache: "cache", quota: "cota", auth: "chave recusada", error: "erro" };

function AddKey({ onDone }: { onDone: () => void }) {
  const [provider, setProvider] = useState<"gemini" | "grok">("gemini");
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [models, setModels] = useState<ModelRow[] | null>(null);
  const [model, setModel] = useState("");
  const [rpm, setRpm] = useState(5);
  const [rpd, setRpd] = useState(100);
  const [allowPaid, setAllowPaid] = useState(false);
  const probe = useMutation({
    mutationFn: () => api<{ models: ModelRow[]; suggested: string | null }>("/ai/models", { method: "POST", json: { provider, api_key: key } }),
    onSuccess: (r) => {
      setModels(r.models);
      setModel(r.suggested ?? r.models[0]?.name ?? "");
    },
  });
  const save = useMutation({
    mutationFn: () =>
      api("/ai/keys", { method: "POST", json: { provider, api_key: key, label, model, rpm_limit: rpm, rpd_limit: rpd, allow_paid: allowPaid, priority: 100 } }),
    onSuccess: () => {
      setKey("");
      setModels(null);
      setLabel("");
      onDone();
    },
  });
  return (
    <Panel title={<><KeyRound size={15} /> Adicionar chave</>}>
      <div className="ai-form">
        <label className="field">Provedor
          <select value={provider} onChange={(e) => { setProvider(e.target.value as "gemini" | "grok"); setModels(null); }}>
            <option value="gemini">Google Gemini (tem nível gratuito)</option>
            <option value="grok">xAI Grok (pago)</option>
          </select>
        </label>
        <label className="field">Nome (opcional)
          <input value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} placeholder="ex.: conta pessoal" />
        </label>
        <label className="field ai-wide">Chave de API
          <input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => { setKey(e.target.value.trim()); setModels(null); }}
            placeholder={provider === "gemini" ? "AIza…" : "xai-…"} />
          <span className="hint">Vai direto para o servidor, é guardada criptografada e nunca mais é exibida.</span>
        </label>
        <div className="row ai-wide">
          <button disabled={key.length < 8 || probe.isPending} onClick={() => probe.mutate()}><Plug size={14} /> {probe.isPending ? "Testando…" : "Testar e listar modelos"}</button>
        </div>
        {models && (
          <>
            <label className="field ai-wide">Modelo
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {models.map((m) => <option key={m.name} value={m.name}>{m.display && m.display !== m.name ? `${m.display} (${m.name})` : m.name}</option>)}
              </select>
              {provider === "gemini" && !models.some((m) => m.name === "gemini-3.8-flash") && (
                <span className="hint">O gemini-3.8-flash não aparece para esta chave; foi sugerido o melhor disponível.</span>
              )}
            </label>
            <label className="field">Limite por minuto
              <input type="number" min={0} value={rpm} onChange={(e) => setRpm(Number(e.target.value))} />
            </label>
            <label className="field">Limite por dia
              <input type="number" min={0} value={rpd} onChange={(e) => setRpd(Number(e.target.value))} />
            </label>
            {provider === "grok" && (
              <label className="row ai-wide" style={{ gap: 6 }}>
                <input type="checkbox" checked={allowPaid} onChange={(e) => setAllowPaid(e.target.checked)} />
                Permitir uso pago desta chave (o Grok não tem nível gratuito; cobra na sua conta xAI)
              </label>
            )}
            <div className="row ai-wide">
              <button className="primary" disabled={!model || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Salvando…" : "Salvar chave"}</button>
            </div>
          </>
        )}
      </div>
      <ErrorNote error={probe.error ?? save.error} />
    </Panel>
  );
}

export function AiSettings() {
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["ai-keys"], queryFn: () => api<AiKey[]>("/ai/keys"), refetchInterval: 10000 });
  const settings = useQuery({ queryKey: ["ai-settings"], queryFn: () => api<Settings>("/ai/settings") });
  const reqs = useQuery({ queryKey: ["ai-requests"], queryFn: () => api<Req[]>("/ai/requests?limit=30"), refetchInterval: 10000 });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: () => api<{ week: { requests: number; tokens: number } }>("/ai/usage"), refetchInterval: 15000 });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ai-keys"] });
    qc.invalidateQueries({ queryKey: ["ai-status"] });
  };
  const patch = useMutation({ mutationFn: ({ id, ...b }: { id: string } & Record<string, unknown>) => api(`/ai/keys/${id}`, { method: "PATCH", json: b }), onSuccess: refresh });
  const del = useMutation({ mutationFn: (id: string) => api(`/ai/keys/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const test = useMutation({ mutationFn: (id: string) => api<{ ok: boolean; error?: string; model_available?: boolean }>(`/ai/keys/${id}/test`, { method: "POST" }), onSuccess: refresh });
  const putSettings = useMutation({
    mutationFn: (b: Partial<Settings>) => api<Settings>("/ai/settings", { method: "PUT", json: b }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["ai-settings"] }); refresh(); },
  });
  const list = keys.data ?? [];
  const s = settings.data;
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    const order = list.map((k) => k.id);
    [order[i], order[j]] = [order[j], order[i]];
    order.forEach((id, n) => patch.mutate({ id, priority: (n + 1) * 10 }));
  };
  const todayTokens = list.reduce((a, k) => a + k.usage.tokens_today, 0);

  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="note">
        As chaves ficam só no servidor (criptografadas). A ordem da lista é a ordem de uso: quando uma chave atinge a cota, o sistema passa para a
        próxima e volta a ela quando a cota renova. {s?.data_notice}
      </div>
      <div className="grid cols-4">
        <Stat label="Chaves ativas" value={list.filter((k) => k.enabled).length} />
        <Stat label="Disponíveis agora" value={list.filter((k) => k.enabled && !k.cooldown_until).length} />
        <Stat label="Tokens hoje" value={todayTokens.toLocaleString("pt-BR")} />
        <Stat label="Pedidos (7 dias)" value={usage.data?.week.requests ?? "—"} hint={`${(usage.data?.week.tokens ?? 0).toLocaleString("pt-BR")} tokens`} />
      </div>

      {s && (
        <Panel title="Comportamento">
          <div className="ai-form">
            <label className="row ai-wide" style={{ gap: 6 }}>
              <input type="checkbox" checked={s.free_only} onChange={(e) => putSettings.mutate({ free_only: e.target.checked })} />
              <strong>Modo exclusivamente gratuito</strong>
              <span className="muted">chaves de provedores pagos (Grok) só são usadas se marcadas "permitir uso pago"</span>
            </label>
            <label className="field">Rodadas de correção (padrão)
              <select value={s.agent_iterations} onChange={(e) => putSettings.mutate({ agent_iterations: Number(e.target.value) })}>
                {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <label className="field">Nota alvo (padrão, 0–10)
              <input type="number" min={0} max={10} step={0.5} defaultValue={s.target_score}
                onBlur={(e) => putSettings.mutate({ target_score: Math.max(0, Math.min(10, Number(e.target.value))) })} />
            </label>
          </div>
          <ErrorNote error={putSettings.error} />
        </Panel>
      )}

      <Panel title="Chaves (em ordem de uso)">
        {list.length === 0 ? (
          <Empty>Nenhuma chave. Crie uma chave do Gemini em aistudio.google.com (botão "Get API key") e adicione abaixo.</Empty>
        ) : (
          <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
            <table>
              <thead>
                <tr><th>#</th><th>Chave</th><th>Modelo</th><th>Uso (min / dia)</th><th>Estado</th><th /></tr>
              </thead>
              <tbody>
                {list.map((k, i) => (
                  <tr key={k.id} className={k.enabled ? "" : "muted"}>
                    <td className="row" style={{ gap: 2 }}>
                      <button className="icon" aria-label="Subir" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={13} /></button>
                      <button className="icon" aria-label="Descer" disabled={i === list.length - 1} onClick={() => move(i, 1)}><ArrowDown size={13} /></button>
                    </td>
                    <td>
                      <strong>{PROVIDER_LABEL[k.provider]}</strong> {k.label && <span className="muted">· {k.label}</span>}
                      <div className="mono muted">{k.key_hint}{k.paid ? " · pago" : ""}</div>
                    </td>
                    <td className="mono">{k.model || "—"}</td>
                    <td className="mono">{k.usage.rpm}/{k.rpm_limit || "∞"} · {k.usage.rpd}/{k.rpd_limit || "∞"}</td>
                    <td>
                      {!k.enabled ? "desativada" : k.paid && s?.free_only && !k.allow_paid ? "bloqueada (modo gratuito)" : k.cooldown_until ? `em espera até ${new Date(k.cooldown_until).toLocaleString("pt-BR")}` : "pronta"}
                      {k.last_error && <div className="check-fail" title={k.last_error}>{k.last_error.slice(0, 90)}</div>}
                    </td>
                    <td className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                      <button onClick={() => test.mutate(k.id)} disabled={test.isPending}>Testar</button>
                      {k.cooldown_until && <button onClick={() => patch.mutate({ id: k.id, clear_cooldown: true })}>Liberar</button>}
                      {k.paid && <button onClick={() => patch.mutate({ id: k.id, allow_paid: !k.allow_paid })}>{k.allow_paid ? "Bloquear pago" : "Permitir pago"}</button>}
                      <button onClick={() => patch.mutate({ id: k.id, enabled: !k.enabled })}>{k.enabled ? "Desativar" : "Ativar"}</button>
                      <button className="icon" aria-label="Remover chave" onClick={() => confirm("Remover esta chave?") && del.mutate(k.id)}><Trash2 size={14} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {test.data && <div className={test.data.ok ? "check-ok" : "check-fail"}>{test.data.ok ? (test.data.model_available === false ? "Chave ok, mas o modelo escolhido não está mais disponível." : "Chave ok.") : test.data.error}</div>}
        <ErrorNote error={patch.error ?? del.error ?? test.error} />
      </Panel>

      <AddKey onDone={refresh} />

      <Panel title="Histórico de pedidos">
        {(reqs.data ?? []).length === 0 ? (
          <Empty>Nenhum pedido ainda.</Empty>
        ) : (
          <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
            <table>
              <thead><tr><th>Quando</th><th>Tarefa</th><th>Modelo</th><th>Resultado</th><th>Tokens</th><th>Tempo</th></tr></thead>
              <tbody>
                {(reqs.data ?? []).map((r) => (
                  <tr key={r.id}>
                    <td>{timeAgo(r.ts)}</td>
                    <td>{r.task === "spec" ? "especificação" : r.task === "critique" ? "comparação" : r.task}</td>
                    <td className="mono">{r.provider}/{r.model}</td>
                    <td className={r.status === "ok" || r.status === "cache" ? "check-ok" : "check-fail"} title={r.error}>{STATUS_LABEL[r.status] ?? r.status}</td>
                    <td className="mono">{r.total_tokens.toLocaleString("pt-BR")}</td>
                    <td className="mono">{r.latency_ms ? `${(r.latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
