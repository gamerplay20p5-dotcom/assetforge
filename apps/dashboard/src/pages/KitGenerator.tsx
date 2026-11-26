import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hammer } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ErrorNote } from "../components/ui";
import type { Worker } from "../types";

export interface KitHouse {
  id: string;
  label: string;
  hint: string;
}

/** Houses of the procedural kit. The first six reproduce the user's reference pack (01_etapas_por_casa). */
export const KIT_HOUSES: KitHouse[] = [
  { id: "ref01", label: "Térrea bege com varanda", hint: "craftsman, telhado verde" },
  { id: "ref02", label: "Sobrado azul", hint: "quatro águas, pórtico" },
  { id: "ref03", label: "Casa amarela em meios níveis", hint: "tijolo + tábuas" },
  { id: "ref04", label: "Moderna telhado inclinado", hint: "uma água, madeira" },
  { id: "ref05", label: "Sobrado de tijolo aparente", hint: "pórtico com pilares" },
  { id: "ref06", label: "Sobrado verde com garagem", hint: "varanda e garagem" },
  { id: "bungalow", label: "Bangalô moderno", hint: "empena de entrada" },
  { id: "tudor_cottage", label: "Cottage Tudor", hint: "enxaimel e pedra" },
  { id: "colonial", label: "Casa colonial", hint: "tábuas, águas-furtadas" },
  { id: "mediterranean", label: "Villa mediterrânea", hint: "arcos e terracota" },
  { id: "nordic_cabin", label: "Cabana nórdica", hint: "vermelho falu" },
  { id: "modern", label: "Casa moderna", hint: "lajes planas" },
];
export const STAGES = ["Terreno", "Fundação", "Estrutura", "Paredes e telhado", "Acabamento", "Finalizada"];

export function KitGenerator({ onCreated }: { onCreated: (ids: string[]) => void }) {
  const qc = useQueryClient();
  const [house, setHouse] = useState("ref01");
  const [stage, setStage] = useState(6);
  const [allStages, setAllStages] = useState(false);
  const [formats, setFormats] = useState<string[]>(["glb", "fbx", "blend"]);
  const workers = useQuery({ queryKey: ["workers"], queryFn: () => api<Worker[]>("/workers"), refetchInterval: 8000 });
  const blenderUp = (workers.data ?? []).some((w) => w.online && w.state === "enabled" && w.capabilities.features?.includes("blender"));
  const cur = KIT_HOUSES.find((h) => h.id === house)!;

  const generate = useMutation({
    mutationFn: async () => {
      const ids: string[] = [];
      for (const s of allStages ? [1, 2, 3, 4, 5, 6] : [stage]) {
        const r = await api<{ id: string }>("/jobs", {
          method: "POST",
          json: {
            name: `${cur.label} · ${s} ${STAGES[s - 1]}`,
            quality_profile: "stylized_detailed",
            formats,
            params: { category: "house", archetype: house, construction_stage: s, texture_resolution: 1024 },
          },
        });
        ids.push(r.id);
      }
      return ids;
    },
    onSuccess: (ids) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onCreated(ids);
    },
  });

  return (
    <>
      <div className="st-title"><Hammer size={16} /> Casa do kit</div>
      <div className="st-hint">Geometria limpa gerada pelo Blender, com os seis estados de obra. Escolha a casa e o estado.</div>
      <div className="kit-grid" role="radiogroup" aria-label="Casa">
        {KIT_HOUSES.map((h) => (
          <button key={h.id} role="radio" aria-checked={house === h.id} className={`kit-card ${house === h.id ? "on" : ""}`} onClick={() => setHouse(h.id)} title={h.hint}>
            <img src={`/kit/${h.id}.jpg`} alt={h.label} loading="lazy" />
            <span>{h.label}</span>
          </button>
        ))}
      </div>
      <div className="st-label">Estado da obra</div>
      <div className="stage-seg" role="radiogroup" aria-label="Estado da obra">
        {STAGES.map((s, i) => (
          <button key={s} role="radio" aria-checked={!allStages && stage === i + 1} disabled={allStages} className={!allStages && stage === i + 1 ? "on" : ""} onClick={() => setStage(i + 1)}>
            <b>{i + 1}</b>
            <small>{s}</small>
          </button>
        ))}
      </div>
      <label className="check">
        <input type="checkbox" checked={allStages} onChange={(e) => setAllStages(e.target.checked)} /> Gerar os 6 estados de uma vez
      </label>
      <div className="row wrap" style={{ gap: 12 }}>
        <span className="muted">Formatos:</span>
        <span className="check muted">GLB</span>
        {["fbx", "blend"].map((f) => (
          <label key={f} className="check">
            <input type="checkbox" checked={formats.includes(f)} onChange={(e) => setFormats(e.target.checked ? [...formats, f] : formats.filter((x) => x !== f))} />
            {f.toUpperCase()}
          </label>
        ))}
      </div>
      <div className="st-foot">
        {!blenderUp && <div className="st-warn">Nenhum worker com Blender está online agora; o pedido ficaria na fila.</div>}
        <ErrorNote error={generate.error} />
        <button className="st-generate" disabled={generate.isPending} onClick={() => generate.mutate()}>
          <Hammer size={18} />
          {generate.isPending ? "Enviando…" : allStages ? "Gerar os 6 estados" : "Gerar casa"}
        </button>
      </div>
    </>
  );
}
