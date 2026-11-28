import { useLocale } from "../i18n";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Upload, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorNote, Panel, Progress } from "../components/ui";
import { parseBatchCsv, parseBatchJson, timeAgo, type BatchItem } from "../lib";
import type { Batch } from "../types";

const EXAMPLE_CSV = `name,category,style,seed,floors,count
Casa residencial,house,classic,100,,20
Supermercado,commercial,modern,200,3,10
Escola,school,classic,300,,5
Hospital,hospital,modern,400,,3
Arranha-céu,skyscraper,modern,500,30,4`;

export function BatchStudio() {
  const { t } = useLocale();
  const qc = useQueryClient();
  const [text, setText] = useState(EXAMPLE_CSV);
  const [kind, setKind] = useState<"csv" | "json">("csv");
  const [name, setName] = useState(t("Lote da cidade"));
  const [priority, setPriority] = useState(0);
  const parsed = kind === "csv" ? parseBatchCsv(text, t) : parseBatchJson(text, t);
  const batches = useQuery({ queryKey: ["batches"], queryFn: () => api<Batch[]>("/batches"), refetchInterval: 4000 });
  const submit = useMutation({
    mutationFn: () => api("/batches", { method: "POST", json: { name, items: parsed.items.map((i: BatchItem) => ({ ...i, priority: i.priority ?? priority })) } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["batches"] }),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`/batches/${id}/cancel`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["batches"] }),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api(`/batches/${id}/retry-failed`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["batches"] }),
  });
  const counts = parsed.items.reduce<Record<string, number>>((a, i) => ((a[String(i.params.category ?? "house")] = (a[String(i.params.category ?? "house")] ?? 0) + 1), a), {});
  return (
    <div className="grid" style={{ gap: 14 }}>
      <div className="grid g2">
        <Panel
          title={t("Importar lista")}
          actions={
            <>
              <select value={kind} onChange={(e) => setKind(e.target.value as "csv" | "json")} style={{ width: 90 }}>
                <option value="csv">CSV</option>
                <option value="json">JSON</option>
              </select>
              <label className="btn">
                <Upload size={14} /> {t("Arquivo")}
                <input
                  type="file"
                  accept=".csv,.json,text/csv,application/json"
                  style={{ display: "none" }}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    setKind(file.name.toLowerCase().endsWith(".json") ? "json" : "csv");
                    setText(await file.text());
                    e.target.value = "";
                  }}
                />
              </label>
            </>
          }
        >
          <textarea rows={11} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label={t("Conteúdo da lista")} />
          <p className="muted" style={{ fontSize: 11 }}>
            {kind === "csv"
              ? t("Colunas: name, category, style, seed, width, depth, floors, floor_height, roof, wear, detail, formats (glb|blend|fbx), quality_profile, priority, count. 'count' expande a linha em N seeds.")
              : t("Formato: [{\"name\":\"Casa 1\",\"params\":{\"category\":\"house\",\"seed\":5}}, …] ou {\"items\":[…]}.")}
          </p>
        </Panel>
        <Panel title={t("Pré-visualização")}>
          {parsed.errors.map((e) => (
            <div className="error-note" key={e}>
              {e}
            </div>
          ))}
          <div className="row wrap" style={{ marginBottom: 8 }}>
            <strong>{parsed.items.length} jobs</strong>
            {Object.entries(counts).map(([c, n]) => (
              <span className="chip" key={c}>
                {c}: {n}
              </span>
            ))}
          </div>
          <div className="table-wrap" style={{ maxHeight: 220 }}>
            <table>
              <thead>
                <tr>
                  <th>{t("Nome")}</th>
                  <th>{t("Categoria")}</th>
                  <th>Seed</th>
                </tr>
              </thead>
              <tbody>
                {parsed.items.slice(0, 50).map((i, n) => (
                  <tr key={n}>
                    <td>{i.name}</td>
                    <td>{String(i.params.category ?? "house")}</td>
                    <td className="mono">{String(i.params.seed ?? 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid g3" style={{ marginTop: 12 }}>
            <label className="field" style={{ gridColumn: "span 2" }}>
              {t("Nome do lote")}
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              {t("Prioridade")}
              <input type="number" value={priority} min={-100} max={100} onChange={(e) => setPriority(Number(e.target.value))} />
            </label>
          </div>
          <ErrorNote error={submit.error} />
          <button className="primary" style={{ marginTop: 12 }} disabled={!parsed.items.length || !!parsed.errors.length || submit.isPending || !name} onClick={() => submit.mutate()}>
            {t("Criar lote com")} {parsed.items.length} {t("jobs rastreáveis")}
          </button>
          {submit.isSuccess && <div className="note" style={{ marginTop: 8 }}>{t("Lote criado. Acompanhe abaixo ou na Queue Manager.")}</div>}
        </Panel>
      </div>
      <Panel title={t("Lotes")}>
        <div className="panel-body flush table-wrap" style={{ margin: -14 }}>
          {batches.data?.length ? (
            <table>
              <thead>
                <tr>
                  <th>{t("Lote")}</th>
                  <th>Jobs</th>
                  <th style={{ width: 200 }}>{t("Progresso")}</th>
                  <th>{t("Criado")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {batches.data.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <Link to={`/queue?batch=${b.id}`}>{b.name}</Link>
                      <div className="muted mono">{b.id}</div>
                    </td>
                    <td>
                      {b.total}
                      <span className="muted" style={{ fontSize: 11 }}>
                        {" "}
                        · ✓{b.counts.succeeded ?? 0} ✗{b.counts.failed ?? 0} ⏵{b.counts.running ?? 0} ⏸{b.counts.queued ?? 0}
                      </span>
                    </td>
                    <td>
                      <Progress value={b.progress} tone={b.finished === b.total ? "ok" : ""} />
                    </td>
                    <td className="muted">{timeAgo(b.created_at, undefined, t)}</td>
                    <td>
                      <div className="row">
                        <button title={t("Cancelar jobs pendentes e em execução")} onClick={() => cancel.mutate(b.id)} disabled={b.finished === b.total}>
                          <XCircle size={14} /> {t("Cancelar")}
                        </button>
                        <button title={t("Repetir os jobs que falharam")} onClick={() => retry.mutate(b.id)} disabled={!b.counts.failed}>
                          <RotateCcw size={14} /> {t("Repetir falhas")}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>{t("Nenhum lote ainda.")}</Empty>
          )}
        </div>
      </Panel>
    </div>
  );
}
