import { useLocale } from "../i18n";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fileUrl } from "../api";
import type { Asset } from "../types";
import { Viewer3D } from "./Viewer3D";
import { ErrorNote } from "./ui";

const views: Record<string, string> = { front: "Frente", right: "Lateral direita", back: "Costas", three_quarter: "Vista 3/4" };
const viewerFlags = { wireframe: false, showBounds: false, autoRotate: false };

export function AssetComparison({ asset, version, token }: { asset: Asset; version: number; token: string | undefined }) {
  const { t } = useLocale();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"reference" | "version">("reference");
  const [reference, setReference] = useState("front");
  const [otherVersion, setOtherVersion] = useState<number>();
  const [renders, setRenders] = useState<string[]>([]);
  const params = asset.manifest?.generation_params ?? {};
  const refs = (params.original_references ?? params.references) as Record<string, string> | undefined ??
    (typeof params.reference_id === "string" ? { front: params.reference_id } : {});
  const references = Object.entries(refs);
  const target = refs[reference] ?? references[0]?.[1];
  const generated = params.generated_reference_file === "reference.png";
  const hasReference = references.length > 0 || generated;
  const versions = (asset.versions ?? []).filter((v) => v.version !== version);
  const other = versions.find((v) => v.version === otherVersion) ?? versions[0];
  const evaluation = useMutation({
    mutationFn: () => api(`/assets/${asset.id}/versions/${version}/evaluate`, { method: "POST", json: { renders } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["asset", asset.id] }),
  });
  const report = asset.manifest?.gemini_evaluation;

  return <>
    <div className="row wrap" style={{ marginBottom: 12 }}>
      <button type="button" onClick={() => setMode("reference")} aria-pressed={mode === "reference"}>{t("Imagens originais")}</button>
      <button type="button" onClick={() => setMode("version")} aria-pressed={mode === "version"} disabled={!versions.length}>{t("Comparar versões")}</button>
    </div>
    <div className="engine-compare">
      <section>
        <div className="engine-compare-heading"><h3>{t("Versão")}{" "}{version}</h3></div>
        <Viewer3D url={token ? fileUrl(asset.id, "model.glb", token, version) : null} {...viewerFlags}
          onCapture={hasReference ? (image) => setRenders((old) => [...old, image].slice(-4)) : undefined} />
      </section>
      <section>
        {mode === "reference" ? <>
          <div className="engine-compare-heading">
            <h3>{generated ? t("Referência gerada") : t("Imagem original")}</h3>
            {references.length > 1 && <select aria-label={t("Vista original")} value={reference} onChange={(e) => setReference(e.target.value)}>
              {references.map(([view]) => <option key={view} value={view}>{t(views[view] ?? view)}</option>)}
            </select>}
          </div>
          {references.length ? <>
            {target && token && <img alt={t(views[reference] ?? "Referência original")}
              src={`/api/v1/references/${encodeURIComponent(target)}?token=${encodeURIComponent(token)}`} />}
          </> : generated && token ? <img alt={t("Referência gerada")} src={fileUrl(asset.id, "reference.png", token, version)} />
            : <p className="muted">{t("Esta versão não tem referências armazenadas.")}</p>}
        </> : <>
          <div className="engine-compare-heading">
            <select aria-label={t("Versão para comparar")} value={other?.version ?? ""} onChange={(e) => setOtherVersion(Number(e.target.value))}>
              {versions.map((v) => <option key={v.version} value={v.version}>v{v.version} · {v.engine}</option>)}
            </select>
          </div>
          <Viewer3D url={token && other ? fileUrl(asset.id, "model.glb", token, other.version) : null} {...viewerFlags} />
        </>}
      </section>
    </div>
    {hasReference && <div className="row wrap" style={{ marginTop: 12 }}>
      <span className="muted">{renders.length}{" "}{t("de 4 vistas capturadas")}</span>
      <button type="button" disabled={!renders.length || evaluation.isPending} onClick={() => evaluation.mutate()}>
        {evaluation.isPending ? t("Avaliando…") : t("Avaliar com Gemini")}
      </button>
      {renders.length > 0 && <button type="button" onClick={() => setRenders([])}>{t("Limpar capturas")}</button>}
    </div>}
    {evaluation.error && <ErrorNote error={evaluation.error} />}
    {report && <section style={{ marginTop: 14 }}>
      <h3>Gemini · {report.overall}/10</h3>
      <p className="muted">{t("Parecer automático ·")}{" "}{report.model}</p>
      <ul>{report.main_differences.map((difference, index) => <li key={index}>{difference}</li>)}</ul>
    </section>}
  </>;
}
