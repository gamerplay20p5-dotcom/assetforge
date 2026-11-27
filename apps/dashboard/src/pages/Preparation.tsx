import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, Panel } from "../components/ui";
import type { Asset, Job } from "../types";

const numbers = (value: string) => value.split(",").map((part) => part.trim() === "" ? NaN : Number(part));

export function Preparation() {
  const [query] = useSearchParams();
  const id = query.get("asset");
  const version = query.get("version");
  const source = useQuery({
    queryKey: ["asset", id, version],
    queryFn: () => api<Asset>(`/assets/${encodeURIComponent(id!)}${version ? `?version=${encodeURIComponent(version)}` : ""}`),
    enabled: !!id,
  });
  return <Panel title="Preparação de assets">
    <p className="muted">Exporte uma versão para Unity com escala em metros, materiais PBR, colisão e arquivos GLB, FBX e BLEND.</p>
    <ErrorNote error={source.error} />
    {source.data?.version_info && source.data.manifest?.generator_id !== "asset.prepare"
      ? <PreparationForm key={`${id}:${version}`} source={source.data} version={source.data.version_info.version} />
      : <p>Selecione uma versão original na <Link to="/library">Biblioteca</Link> e use <strong>Preparar para Unity</strong>.</p>}
  </Panel>;
}

function PreparationForm({ source, version }: { source: Asset; version: number }) {
  const [height, setHeight] = useState("");
  const [rotation, setRotation] = useState("0, 0, 0");
  const [ratios, setRatios] = useState("1");
  const [heights, setHeights] = useState("0");
  const create = useMutation({
    mutationFn: () => {
      const angles = numbers(rotation);
      const lodRatios = numbers(ratios);
      const lodHeights = numbers(heights);
      if (angles.length !== 3 || [...angles, ...lodRatios, ...lodHeights].some((value) => !Number.isFinite(value))) {
        throw new Error("Informe três ângulos e valores válidos para os LODs.");
      }
      return api<Job>("/jobs", { method: "POST", json: {
        name: source.name, asset_id: source.id, job_type: "asset.prepare",
        params: { source_version: version, category: source.category, height_m: Number(height),
          rotation_deg: angles, lod_ratios: lodRatios, lod_heights: lodHeights },
      } });
    },
  });
  return <form onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
    <h3>{source.name} · master v{version}</h3>
    <div className="form-grid">
      <label>Altura real (m)<input type="number" required min="0.001" step="any" value={height} onChange={(e) => setHeight(e.target.value)} /></label>
      <label>Rotação no Blender (X, Y, Z em graus)<input required value={rotation} onChange={(e) => setRotation(e.target.value)} /></label>
      <label>Proporções da malha por LOD<input required value={ratios} onChange={(e) => setRatios(e.target.value)} /></label>
      <label>Altura na tela por LOD (fração)<input required value={heights} onChange={(e) => setHeights(e.target.value)} /></label>
    </div>
    <p className="muted">Comece as proporções em 1. Adicione valores menores apenas se quiser simplificar a geometria nos LODs seguintes.</p>
    <div className="row wrap">
      <button className="primary" disabled={create.isPending}>Enfileirar preparação</button>
      {create.data && <Link to="/queue">Acompanhar preparação</Link>}
    </div>
    <ErrorNote error={create.error} />
  </form>;
}
