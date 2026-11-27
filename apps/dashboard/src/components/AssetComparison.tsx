import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fileUrl } from "../api";
import type { Asset } from "../types";
import { Viewer3D } from "./Viewer3D";
import { ErrorNote } from "./ui";

const views: Record<string, string> = { front: "Frente", right: "Lateral direita", back: "Costas", three_quarter: "Vista 3/4" };
const viewerFlags = { wireframe: false, showBounds: false, autoRotate: false };

export function AssetComparison({ asset, version, token }: { asset: Asset; version: number; token: string | undefined }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"reference" | "version">("reference");
  const [reference, setReference] = useState("front");
  const [otherVersion, setOtherVersion] = useState<number>();
  const [renders, setRenders] = useState<string[]>([]);
  const params = asset.manifest?.generation_params ?? {};
  const refs = params.references as Record<string, string> | undefined ??
    (typeof params.reference_id === "string" ? { front: params.reference_id } : {});
  const references = Object.entries(refs);
  const target = refs[reference] ?? references[0]?.[1];
  const versions = (asset.versions ?? []).filter((v) => v.version !== version);
  const other = versions.find((v) => v.version === otherVersion) ?? versions[0];
  const evaluation = useMutation({
    mutationFn: () => api(`/assets/${asset.id}/versions/${version}/evaluate`, { method: "POST", json: { renders } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["asset", asset.id] }),
  });
  const report = asset.manifest?.gemini_evaluation;

  return <>
    <div className="row wrap" style={{ marginBottom: 12 }}>
      <button type="button" onClick={() => setMode("reference")} aria-pressed={mode === "reference"}>Imagens originais</button>
      <button type="button" onClick={() => setMode("version")} aria-pressed={mode === "version"} disabled={!versions.length}>Comparar versões</button>
    </div>
    <div className="engine-compare">
      <section>
        <h3>Versão {version}</h3>
        <Viewer3D url={token ? fileUrl(asset.id, "model.glb", token, version) : null} {...viewerFlags}
          onCapture={references.length ? (image) => setRenders((old) => [...old, image].slice(-4)) : undefined} />
      </section>
      <section>
        {mode === "reference" ? <>
          <h3>Imagem original</h3>
          {references.length ? <>
            <select aria-label="Vista original" value={reference} onChange={(e) => setReference(e.target.value)}>
              {references.map(([view]) => <option key={view} value={view}>{views[view] ?? view}</option>)}
            </select>
            {target && token && <img alt={views[reference] ?? "Referência original"}
              src={`/api/v1/references/${encodeURIComponent(target)}?token=${encodeURIComponent(token)}`} />}
          </> : <p className="muted">Esta versão não tem referências armazenadas.</p>}
        </> : <>
          <h3>Outra versão</h3>
          <select aria-label="Versão para comparar" value={other?.version ?? ""} onChange={(e) => setOtherVersion(Number(e.target.value))}>
            {versions.map((v) => <option key={v.version} value={v.version}>v{v.version} · {v.engine}</option>)}
          </select>
          <Viewer3D url={token && other ? fileUrl(asset.id, "model.glb", token, other.version) : null} {...viewerFlags} />
        </>}
      </section>
    </div>
    {references.length > 0 && <div className="row wrap" style={{ marginTop: 12 }}>
      <span className="muted">{renders.length} de 4 vistas capturadas</span>
      <button type="button" disabled={!renders.length || evaluation.isPending} onClick={() => evaluation.mutate()}>
        {evaluation.isPending ? "Avaliando…" : "Avaliar com Gemini"}
      </button>
      {renders.length > 0 && <button type="button" onClick={() => setRenders([])}>Limpar capturas</button>}
    </div>}
    {evaluation.error && <ErrorNote error={evaluation.error} />}
    {report && <section style={{ marginTop: 14 }}>
      <h3>Gemini · {report.overall}/10</h3>
      <p className="muted">Parecer automático · {report.model}</p>
      <ul>{report.main_differences.map((difference, index) => <li key={index}>{difference}</li>)}</ul>
    </section>}
  </>;
}
