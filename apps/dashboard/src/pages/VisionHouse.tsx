import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Hammer, ImagePlus, Wand2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, getToken } from "../api";
import { ErrorNote } from "../components/ui";
import { MAX_IMAGE_MB, checkImageFile } from "../imageTo3d";
import { COLOR_HEX, COLOR_LABEL, DEFAULT_DESCRIPTION, POLISH, PORCHES, POSITIONS, ROOF_TYPES, VOLUMES, WALL_MATERIALS, type HouseDescription, type PolishKey } from "../vision";
import { STAGES } from "./KitGenerator";

interface VisionStatus {
  enabled: boolean;
  ready?: boolean;
  loaded?: boolean;
  model?: string;
  reason?: string | null;
}
interface Analysis {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  error: string | null;
  valid?: boolean;
  description?: HouseDescription;
  seconds?: number;
}

function ColorSelect({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="field">
      {label}
      <span className="color-pick">
        <i style={{ background: COLOR_HEX[value] ?? "transparent" }} aria-hidden="true" />
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {Object.keys(COLOR_HEX).map((c) => (
            <option key={c} value={c}>
              {COLOR_LABEL[c]}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}

export function VisionHouse({ onCreated }: { onCreated: (ids: string[]) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [fileErr, setFileErr] = useState<string | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [desc, setDesc] = useState<HouseDescription | null>(null);
  const [aiNote, setAiNote] = useState<string | null>(null);
  const [polish, setPolish] = useState<PolishKey>("polished");
  const [stage, setStage] = useState(6);
  const [allStages, setAllStages] = useState(true);
  const [seed, setSeed] = useState(1);
  const [now, setNow] = useState(Date.now());

  const status = useQuery({ queryKey: ["vision-status"], queryFn: () => api<VisionStatus>("/vision/status"), refetchInterval: 15000 });
  const analysis = useQuery({
    queryKey: ["vision", analysisId],
    queryFn: () => api<Analysis>(`/vision/describe/${analysisId}`),
    enabled: !!analysisId && !desc,
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "succeeded" || q.state.data.status === "failed") ? false : 4000),
  });
  const a = analysis.data;
  const running = !!analysisId && !desc && (!a || a.status === "queued" || a.status === "running");

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);

  useEffect(() => {
    if (!a || a.status === "queued" || a.status === "running" || desc) return;
    if (a.status === "succeeded" && a.valid && a.description) {
      setDesc({ ...DEFAULT_DESCRIPTION, ...a.description });
      setAiNote(`Lido pelo Qwen2.5-VL em ${Math.round(a.seconds ?? 0)} s. Confira os campos: o modelo costuma errar janelas, volumes e o tipo de telhado.`);
    } else {
      setDesc({ ...DEFAULT_DESCRIPTION });
      setAiNote(a.status === "failed" ? `A análise falhou (${a.error}). Preencha à mão.` : `A resposta do modelo não passou na validação (${a.error ?? "inválida"}). Preencha à mão.`);
    }
  }, [a, desc]);

  const pick = (f: File | undefined) => {
    if (!f) return;
    const err = checkImageFile(f);
    setFileErr(err);
    if (err) return;
    setFile(f);
    setUrl(URL.createObjectURL(f));
    setAnalysisId(null);
    setDesc(null);
  };
  // Ctrl+V: a pasted screenshot becomes the reference
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      for (const it of Array.from(e.clipboardData?.items ?? [])) {
        if (it.kind === "file" && it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) {
            e.preventDefault();
            pick(new File([f], `print-${Date.now()}.${f.type.split("/")[1] || "png"}`, { type: f.type }));
            return;
          }
        }
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  const analyze = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append("file", file!);
      const up = await fetch("/api/v1/references", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
      const ref = await up.json().catch(() => ({}));
      if (!up.ok) throw new Error(typeof ref.detail === "string" ? ref.detail : `falha no upload (${up.status})`);
      return api<{ id: string }>("/vision/describe", { method: "POST", json: { reference_id: ref.id } });
    },
    onSuccess: (r) => {
      setStartedAt(Date.now());
      setAnalysisId(r.id);
    },
  });

  const preview = useQuery({
    queryKey: ["vision-preview", desc, seed],
    queryFn: () => api<{ base: string; base_label: string }>("/vision/preview", { method: "POST", json: { description: desc, seed } }),
    enabled: !!desc,
    retry: false,
  });

  const set = <K extends keyof HouseDescription>(k: K, v: HouseDescription[K]) => setDesc((d) => (d ? { ...d, [k]: v } : d));
  const setFloors = (n: number) =>
    setDesc((d) => (d ? { ...d, floors: n, windows_front_per_floor: Array.from({ length: n }, (_, i) => d.windows_front_per_floor[i] ?? 2) } : d));
  const win = (i: number, v: number) => setDesc((d) => (d ? { ...d, windows_front_per_floor: d.windows_front_per_floor.map((n, j) => (j === i ? v : n)) } : d));

  const generate = useMutation({
    mutationFn: async () => {
      const p = POLISH[polish];
      const ids: string[] = [];
      for (const s of allStages ? [1, 2, 3, 4, 5, 6] : [stage]) {
        const r = await api<{ id: string }>("/jobs", {
          method: "POST",
          json: {
            name: `Casa (IA) · ${s} ${STAGES[s - 1]}`,
            quality_profile: "stylized_detailed",
            formats: ["glb", "fbx", "blend"],
            params: { category: "house", house_description: desc, construction_stage: s, texture_resolution: p.texture, wear: p.wear, seed },
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

  const elapsed = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;
  const off = !!status.data && (!status.data.enabled || status.data.ready === false);

  return (
    <>
      <div className="st-title">
        <Eye size={16} /> Imagem → casa (IA)
      </div>
      <div className="st-hint">O Qwen2.5-VL (local, em CPU) lê a imagem e descreve a casa. Você confere, corrige, e o kit procedural monta o modelo e os 6 estados de obra.</div>
      {off && <div className="st-warn">Serviço de visão indisponível: {status.data?.reason ?? "desligado"}. Você ainda pode preencher a descrição à mão.</div>}

      <div
        className="dropzone small"
        role="button"
        tabIndex={0}
        aria-label="Escolher a imagem da casa"
        onClick={() => input.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      >
        {url ? (
          <div className="vis-prev">
            <img src={url} alt="Imagem de referência" />
            <button
              className="icon x"
              aria-label="Remover imagem"
              onClick={(e) => {
                e.stopPropagation();
                setFile(null);
                setUrl(null);
                setAnalysisId(null);
                setDesc(null);
              }}
            >
              <X size={12} />
            </button>
          </div>
        ) : (
          <>
            <ImagePlus size={26} />
            <strong>Enviar ou colar a imagem da casa</strong>
            <span>Clique, arraste ou use Ctrl+V · até {MAX_IMAGE_MB} MB</span>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>
      {fileErr && <div className="check-fail">{fileErr}</div>}

      {!desc && (
        <div className="row wrap" style={{ gap: 8 }}>
          <button className="primary" disabled={!file || analyze.isPending || running || off} onClick={() => analyze.mutate()}>
            <Wand2 size={15} /> {running ? `Analisando… ${elapsed}s` : "Analisar com IA"}
          </button>
          <button
            onClick={() => {
              setDesc({ ...DEFAULT_DESCRIPTION });
              setAiNote("Descrição inicial sem IA. Preencha os campos.");
            }}
          >
            Preencher à mão
          </button>
        </div>
      )}
      {running && <div className="st-hint">O 7B em CPU leva uns 3 a 4 minutos por imagem. A análise continua no servidor mesmo se você trocar de aba.</div>}
      <ErrorNote error={analyze.error ?? analysis.error} />

      {desc && (
        <>
          {aiNote && <div className="st-hint">{aiNote}</div>}
          <div className="vis-base">
            {preview.data ? (
              <>
                <img src={`/kit/${preview.data.base}.jpg`} alt="" />
                <div>
                  <div className="st-label" style={{ margin: 0 }}>
                    Será montada sobre
                  </div>
                  <strong>{preview.data.base_label}</strong>
                </div>
              </>
            ) : (
              <div className="st-hint">{preview.isError ? "Descrição inválida." : "Calculando a base…"}</div>
            )}
          </div>
          <div className="st-fields">
            <label className="field">
              Andares
              <select value={desc.floors} onChange={(e) => setFloors(Number(e.target.value))}>
                {[1, 2, 3].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Telhado
              <select value={desc.roof_type} onChange={(e) => set("roof_type", e.target.value)}>
                {ROOF_TYPES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <ColorSelect label="Cor do telhado" value={desc.roof_color} onChange={(v) => set("roof_color", v)} />
            <label className="field">
              Parede
              <select value={desc.wall_material} onChange={(e) => set("wall_material", e.target.value)}>
                {WALL_MATERIALS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <ColorSelect label="Cor da parede" value={desc.wall_color} onChange={(v) => set("wall_color", v)} />
            <ColorSelect label="Cor dos frisos" value={desc.trim_color} onChange={(v) => set("trim_color", v)} />
            <ColorSelect label="Cor da porta" value={desc.door_color} onChange={(v) => set("door_color", v)} />
            <label className="field">
              Porta
              <select value={desc.door_position} onChange={(e) => set("door_position", e.target.value)}>
                {POSITIONS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Varanda
              <select value={desc.porch} onChange={(e) => set("porch", e.target.value)}>
                {PORCHES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Volumes
              <select value={desc.volumes} onChange={(e) => set("volumes", e.target.value)}>
                {VOLUMES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <div className="row wrap" style={{ gridColumn: "1 / -1", gap: 14 }}>
              <label className="check">
                <input
                  type="checkbox"
                  checked={desc.lower_wall_material === "brick"}
                  onChange={(e) => setDesc((d) => (d ? { ...d, lower_wall_material: e.target.checked ? "brick" : "none", lower_wall_color: e.target.checked ? "brick_red" : "none" } : d))}
                />
                Tijolo embaixo
              </label>
              <label className="check">
                <input type="checkbox" checked={desc.garage} onChange={(e) => setDesc((d) => (d ? { ...d, garage: e.target.checked, garage_side: e.target.checked ? "right" : "none" } : d))} />
                Garagem
              </label>
              <label className="check">
                <input type="checkbox" checked={desc.chimney} onChange={(e) => set("chimney", e.target.checked)} />
                Chaminé
              </label>
              <label className="check">
                <input type="checkbox" checked={desc.bay_window} onChange={(e) => set("bay_window", e.target.checked)} />
                Janela em bay
              </label>
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              Janelas na frente, por andar
              <span className="row" style={{ gap: 10 }}>
                {desc.windows_front_per_floor.map((n, i) => (
                  <label key={i} className="row" style={{ gap: 4 }}>
                    <span className="muted">{i + 1}º</span>
                    <input type="number" min={0} max={6} style={{ width: 56 }} value={n} onChange={(e) => win(i, Math.max(0, Math.min(6, Number(e.target.value))))} />
                  </label>
                ))}
              </span>
            </div>
          </div>

          <div className="st-label">Acabamento</div>
          <div className="seg two" role="radiogroup" aria-label="Acabamento">
            {(Object.keys(POLISH) as PolishKey[]).map((k) => (
              <button key={k} role="radio" aria-checked={polish === k} className={polish === k ? "on" : ""} onClick={() => setPolish(k)}>
                {POLISH[k].label}
              </button>
            ))}
          </div>
          <div className="st-hint">
            {POLISH[polish].hint}. Variação:{" "}
            <input type="number" min={0} style={{ width: 70, display: "inline-block" }} value={seed} onChange={(e) => setSeed(Math.max(0, Number(e.target.value)))} aria-label="Semente de variação" /> (muda os
            arbustos e detalhes pequenos).
          </div>
          <label className="check">
            <input type="checkbox" checked={allStages} onChange={(e) => setAllStages(e.target.checked)} /> Gerar os 6 estados de obra
          </label>
          {!allStages && (
            <select value={stage} onChange={(e) => setStage(Number(e.target.value))} aria-label="Estado da obra">
              {STAGES.map((s, i) => (
                <option key={s} value={i + 1}>
                  {i + 1} · {s}
                </option>
              ))}
            </select>
          )}
          <div className="st-foot">
            <ErrorNote error={generate.error} />
            <button className="st-generate" disabled={generate.isPending || preview.isError} onClick={() => generate.mutate()}>
              <Hammer size={18} /> {generate.isPending ? "Enviando…" : allStages ? "Gerar a casa nos 6 estados" : "Gerar a casa"}
            </button>
          </div>
        </>
      )}
    </>
  );
}
