import { useLocale } from "../i18n";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import { geometryProfile, geometryProfiles, type GeometryProfile } from "../geometryProfiles";
import type { Asset, Job, Worker } from "../types";

const numbers = (value: string) => value.split(",").map((part) => part.trim() === "" ? NaN : Number(part));

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
      ? <PreparationForm key={`${id}:${version}:${profile}`} source={source.data} version={source.data.version_info.version} initialProfile={profile} />
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
  const [heights, setHeights] = useState("0");
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers") });
  const compatible = (workers.data ?? []).filter((worker) => worker.online && worker.state === "enabled"
    && worker.capabilities.features?.includes("asset.prepare")
    && (!(numbers(ratios)[0] < 1) || worker.capabilities.features.includes("asset.prepare-density")));
  const selectedWorkerId = compatible.some((worker) => worker.id === workerId) ? workerId : "";
  const create = useMutation({
    mutationFn: () => {
      const angles = numbers(rotation);
      const lodRatios = numbers(ratios);
      const lodHeights = numbers(heights);
      if (angles.length !== 3 || [...angles, ...lodRatios, ...lodHeights].some((value) => !Number.isFinite(value))) {
        throw new Error(t("Informe três ângulos e valores válidos para os LODs."));
      }
      return api<Job>("/jobs", { method: "POST", json: {
        name: source.name, asset_id: source.id, job_type: "asset.prepare", worker_id: selectedWorkerId || undefined,
        params: { source_version: version, category: source.category, height_m: Number(height),
          rotation_deg: angles, lod_ratios: lodRatios, lod_heights: lodHeights },
      } });
    },
  });
  return <form onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <h3>{source.name} · master v{version}</h3>
    <div className="form-grid">
      <label>{t("Perfil geométrico")}<select value={profile} onChange={(event) => {
        const next = geometryProfile(event.target.value);
        setProfile(next);
        setRatios(String(geometryProfiles[next].ratio));
        setHeights("0");
      }}>
        {Object.entries(geometryProfiles).map(([id, option]) => <option key={id} value={id}>{t(option.label)}</option>)}
      </select></label>
      <label>{t("Altura real (m)")}<input type="number" required min="0.001" step="any" value={height} onChange={(e) => setHeight(e.target.value)} /></label>
      <label>{t("Rotação no Blender (X, Y, Z em graus)")}<input required value={rotation} onChange={(e) => setRotation(e.target.value)} /></label>
      <label>{t("Proporções da malha por LOD")}<input required value={ratios} onChange={(e) => setRatios(e.target.value)} /></label>
      <label>{t("Altura na tela por LOD (fração)")}<input required value={heights} onChange={(e) => setHeights(e.target.value)} /></label>
    </div>
    <details className="af-settings">
      <summary>{t("Ajustes avançados")}</summary>
      <label className="field">{t("Worker")}<select value={selectedWorkerId}
        onChange={(event) => setWorkerId(event.target.value)}>
        <option value="">{t("Automático")}</option>
        {compatible.map((worker) => <option value={worker.id} key={worker.id}>{worker.name}</option>)}
      </select></label>
    </details>
    <p className="muted">{t("Cada proporção tem como base o master. Use 1 para manter a geometria integral ou ajuste o valor do primeiro LOD para simplificar esta versão.")}</p>
    <div className="row wrap">
      <button className="primary" disabled={create.isPending}>{t("Enfileirar preparação")}</button>
      {create.data?.status === "succeeded" && create.data.asset_version
        ? <Link to={`/library/${source.id}?version=${create.data.asset_version}`}>{t("Abrir versão preparada")}</Link>
        : create.data && <Link to="/queue">{t("Acompanhar preparação")}</Link>}
    </div>
    <ErrorNote error={create.error} />
  </form>;
}
