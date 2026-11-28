import { useLocale } from "../i18n";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import { geometryProfile, geometryProfiles, type GeometryProfile } from "../geometryProfiles";
import type { Asset, Job, Worker } from "../types";

const numbers = (value: string) => value.split(",").map((part) => part.trim() === "" ? NaN : Number(part));
const methods = {
  auto: "Automático por geometria",
  hybrid: "Híbrido de planos e arestas",
  voxel: "Retopologia voxel com baking",
  instant: "Instant Meshes · experimental",
  quadri: "QuadriFlow · experimental",
  conservative: "gltfpack · preservação de atributos",
  legacy: "Exportação clássica",
} as const;
type Method = keyof typeof methods;
const budgets: Record<string, readonly number[]> = {
  building: [8000, 2400, 600], vehicle: [6000, 1800, 450], npc: [4000, 1200, 300], prop: [4000, 1200, 300],
};
function targetsFor(category: string, profile: GeometryProfile) {
  const multiplier = profile === "high" ? 4 : profile === "mid" ? 2 : 1;
  return (budgets[category] ?? budgets.prop).map((target) => String(target * multiplier));
}

export function Preparation() {
  const { t } = useLocale();
  const [query] = useSearchParams();
  const id = query.get("asset");
  const version = query.get("version");
  const profile = geometryProfile(query.get("profile"));
  const source = useQuery({
    queryKey: ["asset", id, version],
    queryFn: () => api<Asset>(`/assets/${encodeURIComponent(id!)}${version ? `?version=${encodeURIComponent(version)}` : ""}`),
    enabled: !!id,
  });
  return <Panel title={t("Preparação de assets")}>
    <p className="muted">{t("Exporte uma versão para Unity com escala em metros, materiais PBR, colisão e arquivos GLB, FBX e BLEND.")}</p>
    <ErrorNote error={source.error} />
    {source.data?.version_info && source.data.manifest?.generator_id !== "asset.prepare"
      ? <PreparationForm key={`${id}:${version}:${query.get("profile")}`} source={source.data} version={source.data.version_info.version}
          initialProfile={query.has("profile") ? profile : "low"} />
      : <p>{t("Selecione uma versão original na")}{" "}<Link to="/library">{t("Biblioteca")}</Link>{" "}{t("e use")}{" "}<strong>{t("Preparar para Unity")}</strong>.</p>}
  </Panel>;
}

function PreparationForm({ source, version, initialProfile }: { source: Asset; version: number; initialProfile: GeometryProfile }) {
  const { t } = useLocale();
  const [height, setHeight] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [rotation, setRotation] = useState("0, 0, 0");
  const [profile, setProfile] = useState<GeometryProfile>(initialProfile);
  const [ratios, setRatios] = useState(String(geometryProfiles[initialProfile].ratio));
  const [method, setMethod] = useState<Method>(initialProfile === "master" ? "legacy" : "auto");
  const [targets, setTargets] = useState(() => targetsFor(source.category, initialProfile));
  const [heights, setHeights] = useState(initialProfile === "master" ? "0" : "0.50, 0.16, 0.04");
  const [bakeSize, setBakeSize] = useState(512);
  const [impostor, setImpostor] = useState(true);
  const [projection, setProjection] = useState<"adaptive" | "fixed">("adaptive");
  const optimized = method !== "legacy";
  const lodTargets = targets.map(Number);
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers") });
  const compatible = (workers.data ?? []).filter((worker) => worker.online && worker.state === "enabled"
    && worker.capabilities.features?.includes("asset.prepare")
    && (optimized
      ? worker.capabilities.features.includes("asset.prepare-optimization")
        && (method !== "instant" || worker.capabilities.features.includes("asset.prepare-instant"))
      : (!(numbers(ratios)[0] < 1) || worker.capabilities.features.includes("asset.prepare-density"))));
  const selectedWorkerId = compatible.some((worker) => worker.id === workerId) ? workerId : "";
  const create = useMutation({
    mutationFn: () => {
      const angles = numbers(rotation);
      const lodRatios = numbers(ratios);
      const lodHeights = numbers(heights);
      if (angles.length !== 3 || [...angles, ...lodRatios, ...lodHeights].some((value) => !Number.isFinite(value))) {
        throw new Error(t("Informe três ângulos e valores válidos para os LODs."));
      }
      if (optimized && (lodHeights.length !== lodTargets.length || lodTargets.some((n, i) => !Number.isInteger(n) || n < 4 || (i > 0 && n >= lodTargets[i - 1])))) {
        throw new Error(t("Use um alvo inteiro decrescente para cada LOD."));
      }
      return api<Job>("/jobs", { method: "POST", json: {
        name: source.name, asset_id: source.id, job_type: "asset.prepare", worker_id: selectedWorkerId || undefined,
        params: { source_version: version, category: source.category, height_m: Number(height),
          rotation_deg: angles, lod_heights: lodHeights,
          ...(optimized ? { method, triangle_targets: lodTargets, bake_size: bakeSize, projection, impostor } : { lod_ratios: lodRatios }) },
      } });
    },
  });
  return <form className="asset-preparation" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <h3>{source.name} · master v{version}</h3>
    <div className="form-grid">
      <label>{t("Perfil geométrico")}<select value={profile} onChange={(event) => {
        const next = geometryProfile(event.target.value);
        setProfile(next);
        setRatios(String(geometryProfiles[next].ratio));
        if (next === "master") {
          setMethod("legacy");
          setHeights("0");
        } else {
          if (!optimized) {
            setMethod("auto");
            setHeights("0.50, 0.16, 0.04");
          }
          setTargets(targetsFor(source.category, next));
        }
      }}>
        {Object.entries(geometryProfiles).map(([id, option]) => <option key={id} value={id}>{t(option.label)}</option>)}
      </select></label>
      <label>{t("Altura real (m)")}<input type="number" required min="0.001" step="any" value={height} onChange={(e) => setHeight(e.target.value)} /></label>
      <label>{t("Método de otimização")}<select value={method} onChange={(event) => {
        const next = event.target.value as Method;
        setMethod(next);
        if ((next === "legacy") === optimized) setHeights(next === "legacy" ? "0" : "0.50, 0.16, 0.04");
        if (next !== "legacy" && profile === "master") {
          setProfile("low");
          setTargets(targetsFor(source.category, "low"));
        }
      }}>
        {Object.entries(methods).map(([id, label]) => <option key={id} value={id}>{t(label)}</option>)}
      </select></label>
    </div>
    {optimized && <fieldset className="af-lod-targets">
      <legend>{t("Alvos de triângulos")}</legend>
      <div className="form-grid">
        {targets.map((value, i) => <label key={i}>LOD{i}<input value={value} onChange={(event) =>
          setTargets((old) => old.map((target, j) => j === i ? event.target.value : target))}
          required type="number" min="4" step="1" /></label>)}
      </div>
      <p className="muted">{t("A qualidade tem prioridade. Se o alvo for excedido, a comparação mostra a malha preservada e as tentativas.")}</p>
      <label className="row"><input type="checkbox" checked={impostor} onChange={(e) => setImpostor(e.target.checked)} />{t("Gerar impostor de 8 vistas")}</label>
    </fieldset>}
    <details className="af-settings">
      <summary>{t("Ajustes avançados")}</summary>
      <div className="form-grid">
        <label>{t("Rotação no Blender (X, Y, Z em graus)")}<input required value={rotation} onChange={(e) => setRotation(e.target.value)} /></label>
        <label>{t("Altura na tela por LOD (fração)")}<input required value={heights} onChange={(e) => setHeights(e.target.value)} /></label>
        {optimized ? <>
          <label>{t("Textura de baking (px)")}<select value={bakeSize} onChange={(e) => setBakeSize(Number(e.target.value))}>
            {[256, 512, 1024, 2048].map((size) => <option key={size}>{size}</option>)}
          </select></label>
          <label>{t("Projeção de textura")}<select value={projection} onChange={(e) => setProjection(e.target.value as typeof projection)}>
            <option value="adaptive">{t("Cage adaptativo")}</option><option value="fixed">{t("Distância fixa")}</option>
          </select></label>
        </> : <label>{t("Proporções da malha por LOD")}<input required value={ratios} onChange={(e) => setRatios(e.target.value)} /></label>}
        <label>{t("Worker")}<select value={selectedWorkerId} onChange={(event) => setWorkerId(event.target.value)}>
          <option value="">{t("Automático")}</option>
          {compatible.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}
        </select></label>
      </div>
    </details>
    {workers.isSuccess && !compatible.length && <p className="muted">{t("Nenhum worker compatível está online. A preparação aguardará na fila.")}</p>}
    <div className="row wrap">
      <button className="primary" disabled={create.isPending}>{t("Enfileirar preparação")}</button>
      {create.data?.status === "succeeded" && create.data.asset_version
        ? <Link to={`/library/${source.id}?version=${create.data.asset_version}`}>{t("Abrir versão preparada")}</Link>
        : create.data && <Link to="/queue">{t("Acompanhar preparação")}</Link>}
    </div>
    <ErrorNote error={create.error} />
  </form>;
}
