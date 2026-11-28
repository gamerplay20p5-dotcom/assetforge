import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fileUrl } from "../api";
import { useLocale } from "../i18n";
import type { Asset } from "../types";
import { Viewer3D } from "./Viewer3D";
import { ErrorNote } from "./ui";

type Score = { silhouette_iou: number; interior_missing: number; color_mae: number; dark_patches: number; new_edges: number;
  regions: Record<string, { edge_recall: number | null; silhouette_missing: number }> };
type Attempt = { method: string; projection: string | null; triangles?: number; issues: string[];
  surface_drift_p95?: number; projection_miss?: number | null; views?: Record<string, Score>; preview_prefix?: string };
type Quality = { views: string[]; levels: {
  index: number; target: number; triangles: number; bytes: number; target_met: boolean; selected_method: string;
  accepted: Attempt; attempts: Attempt[];
}[] };
type Atlas = { frames: { azimuth_degrees: number; x: number; y: number }[]; columns: number; rows: number; tile_size: number };

const viewLabels: Record<string, string> = { front: "Frente", side: "Lateral", rear: "Costas", top: "Topo" };
const methods: Record<string, string> = { hybrid: "Híbrido de planos e arestas", voxel: "Retopologia voxel com baking",
  instant: "Instant Meshes · experimental", quadri: "QuadriFlow · experimental", conservative: "gltfpack · preservação de atributos",
  conservative_previous: "gltfpack · a partir do nível anterior",
  preserve_master: "Geometria do master preservada", reuse_previous: "Malha do nível anterior preservada" };
const findings: Record<string, string> = { silhouette_iou: "Silhueta abaixo do limiar", interior_missing: "Aberturas ou partes ausentes",
  color_mae: "Diferença de cores e materiais", dark_patches: "Manchas escuras", new_edges: "Arestas de contraste novas",
  projection_miss: "Amostras de projeção sem interseção", surface_drift_p95: "Desvio de superfície",
  geometry_ceiling: "Mais triângulos que o nível anterior", method_failed: "Falha do método", regional_detail: "Perda de detalhe regional" };
const regions: Record<string, string> = { doors: "Portas", windows: "Janelas", wheels: "Rodas", limbs: "Membros", arms: "Braços", edges: "Arestas" };
const viewerFlags = { wireframe: false, showBounds: false, autoRotate: false };

export function OptimizationComparison({ asset, version, token }: { asset: Asset; version: number; token?: string }) {
  const { t, language } = useLocale();
  const [level, setLevel] = useState(0);
  const [view, setView] = useState("front");
  const [matched, setMatched] = useState(false);
  const [frameIndex, setFrameIndex] = useState(0);
  const [attemptIndex, setAttemptIndex] = useState<number>();
  const master = Number(asset.manifest?.provenance.source_version);
  const lods = asset.manifest?.lods ?? [];
  const hasAtlas = !!(asset.files ?? asset.manifest?.textures.map((name) => ({ name })))?.some((file) => file.name === "impostor/atlas.png");
  const getFile = (name: string, from = version) => fileUrl(asset.id, name, token, from);
  const report = useQuery({
    queryKey: ["optimization", asset.id, version],
    enabled: !!token,
    queryFn: async (): Promise<Quality> => {
      const response = await fetch(getFile("quality.json"));
      if (!response.ok) throw new Error(t("Falha ao ler o controle de qualidade."));
      return response.json();
    },
  });
  const atlas = useQuery({
    queryKey: ["impostor-atlas", asset.id, version],
    enabled: !!token && hasAtlas && level === -1,
    queryFn: async (): Promise<Atlas> => {
      const response = await fetch(getFile("impostor/atlas.json"));
      if (!response.ok) throw new Error(t("Falha ao ler o atlas do impostor."));
      return response.json();
    },
  });
  const entry = report.data?.levels.find((item) => item.index === level);
  const attempt = attemptIndex === undefined ? undefined : entry?.attempts[attemptIndex];
  const checked = attempt ?? entry?.accepted;
  const score = checked?.views?.[view];
  const derived = lods.find((item) => item.level === level);
  const frame = atlas.data?.frames[frameIndex];
  const percent = (value: number) => new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 }).format(value);
  const triangleCount = (count: number) => new Intl.NumberFormat(language).format(count);
  return <div className="af-optimization-compare">
    <div className="row wrap">
      {lods.map((lod) => <button type="button" key={lod.level} aria-pressed={level === lod.level} onClick={() => {
        setLevel(lod.level);
        setAttemptIndex(undefined);
      }}>LOD{lod.level}</button>)}
      {hasAtlas && <button type="button" aria-pressed={level === -1} onClick={() => setLevel(-1)}>{t("Impostor")}</button>}
      {level >= 0 && <button type="button" aria-pressed={matched} onClick={() => {
        setAttemptIndex(undefined);
        setMatched((current) => !current);
      }}>{t("Vistas alinhadas")}</button>}
      {matched && level >= 0 && <select aria-label={t("Vista")} value={view} onChange={(event) => setView(event.target.value)}>
        {report.data?.views.map((name) => <option value={name} key={name}>{t(viewLabels[name] ?? name)}</option>)}
      </select>}
    </div>
    <div className="engine-compare">
      <section>
        <div className="engine-compare-heading"><h3>Master v{master}</h3></div>
        {matched && level >= 0 && token && report.data ? <img alt={`Master · ${t(viewLabels[view])}`} src={getFile(`quality/master-${view}.png`)} />
          : <Viewer3D url={token && master > 0 ? getFile("model.glb", master) : null} {...viewerFlags} />}
      </section>
      <section>
        <div className="engine-compare-heading"><h3>{level < 0 ? t("Impostor") : attempt ? t("Tentativa sinalizada") : `LOD${level}`}</h3>
          {derived && <span className="muted">{triangleCount(attempt?.triangles ?? derived.triangles)} {"△"}</span>}
        </div>
        {level < 0 ? <>
          <ErrorNote error={atlas.error} />
          {frame && atlas.data && <div className="af-impostor-frame" role="img" aria-label={`${t("Impostor")} · ${frame.azimuth_degrees}°`}
            style={{ backgroundImage: `url("${getFile("impostor/atlas.png")}")`,
              backgroundSize: `${atlas.data.columns * 100}% ${atlas.data.rows * 100}%`,
              backgroundPosition: `${frame.x / atlas.data.tile_size / (atlas.data.columns - 1) * 100}% ${(1 - frame.y / atlas.data.tile_size / (atlas.data.rows - 1)) * 100}%` }} />}
          {atlas.data && <label className="field">{t("Ângulo do impostor")}
            <select value={frameIndex} onChange={(event) => setFrameIndex(Number(event.target.value))}>
              {atlas.data.frames.map((item, i) => <option key={item.azimuth_degrees} value={i}>{item.azimuth_degrees}°</option>)}
            </select></label>}
        </> : matched && token && report.data ? <img alt={`LOD${level} · ${t(viewLabels[view])}`}
          src={getFile(`quality/${attempt?.preview_prefix ?? `lod${level}`}-${view}.png`)} />
          : <Viewer3D url={token && derived ? getFile(derived.file) : null} {...viewerFlags} />}
      </section>
    </div>
    <ErrorNote error={report.error} />
    {entry && <section className="af-quality">
      <h3>{t("Controle de qualidade")}</h3>
      <p>{t(methods[entry.accepted.method] ?? entry.accepted.method)} · {t("Alvo")} {triangleCount(entry.target)} {"△"}
        {" · "}{t(entry.target_met ? "Alvo atingido" : "Acima do alvo para preservar qualidade")}</p>
      <p className="muted">{t("As regiões são indicativas. Confira elementos arquitetônicos e partes móveis nas vistas alinhadas.")}</p>
      {score && <dl className="af-quality-scores">
        <div><dt>{t("Silhueta")}</dt><dd>{percent(score.silhouette_iou)}</dd></div>
        <div><dt>{t("Diferença de cores e materiais")}</dt><dd>{percent(score.color_mae)}</dd></div>
        <div><dt>{t("Aberturas ou partes ausentes")}</dt><dd>{percent(score.interior_missing)}</dd></div>
        <div><dt>{t("Manchas escuras")}</dt><dd>{percent(score.dark_patches)}</dd></div>
        {typeof checked?.surface_drift_p95 === "number" &&
          <div><dt>{t("Desvio de superfície")}</dt><dd>{percent(checked.surface_drift_p95)}</dd></div>}
        {typeof checked?.projection_miss === "number" &&
          <div><dt>{t("Amostras de projeção sem interseção")}</dt><dd>{percent(checked.projection_miss)}</dd></div>}
        {Object.entries(score.regions).map(([name, region]) => <div key={name}><dt>{t(regions[name] ?? name)}</dt>
          <dd>{region.edge_recall === null ? "–" : percent(region.edge_recall)} {t("de arestas preservadas")}</dd></div>)}
      </dl>}
      {entry.accepted.issues.length > 0 && <p>{entry.accepted.issues.map((issue) => t(findings[issue] ?? issue)).join(" · ")}</p>}
      <details className="af-settings"><summary>{t("Métodos avaliados")}</summary>
        <ul>{entry.attempts.map((candidate, i) => <li key={i}>
          {t(methods[candidate.method] ?? candidate.method)}
          {candidate.projection && ` · ${t(candidate.projection === "adaptive" ? "Cage adaptativo" : "Distância fixa")}`}
          {candidate.triangles != null && ` · ${triangleCount(candidate.triangles)} △`}
          {candidate.issues.length > 0 && ` · ${candidate.issues.map((issue) => t(findings[issue] ?? issue)).join(" · ")}`}
          {candidate.preview_prefix && <>{" "}<button type="button" aria-pressed={attemptIndex === i} onClick={() => {
            setAttemptIndex(attemptIndex === i ? undefined : i);
            setMatched(true);
          }}>{t(attemptIndex === i ? "Voltar ao LOD publicado" : "Ver tentativa")}</button></>}
        </li>)}</ul>
      </details>
      {token && <a href={fileUrl(asset.id, "quality.json", token, version, true)}>{t("Baixar medições completas")}</a>}
    </section>}
  </div>;
}
