import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ImagePlus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, getToken } from "../api";
import { ErrorNote } from "../components/ui";
import { MAX_IMAGE_MB, checkImageFile } from "../imageTo3d";
import { POLISH, type PolishKey } from "../vision";

export interface AiStatus {
  configured: boolean;
  available: number;
  next_available_at: string | null;
  blocked: string[];
  free_only: boolean;
  agent_iterations: number;
  target_score: number;
}

interface Pic {
  key: string;
  file: File;
  url: string;
}

const CATEGORIES: [string, string][] = [
  ["house", "Casa / sobrado"],
  ["apartment", "Prédio residencial"],
  ["skyscraper", "Arranha-céu"],
  ["commercial", "Comercial / loja"],
  ["school", "Escola"],
  ["hospital", "Hospital"],
  ["industrial", "Industrial"],
  ["warehouse", "Galpão"],
  ["government", "Governo"],
  ["police", "Delegacia"],
  ["fire_station", "Bombeiros"],
  ["transport_station", "Estação"],
  ["university", "Universidade"],
];
/** Not buildings: the cloud agent writes a procedural BUILDING spec, so these cannot be produced here. They belong to the 3D reconstruction engines (Pixal3D / TRELLIS.2),
 *  which are not wired to this panel yet. Listed (disabled) so the roadmap is visible instead of silently missing. */
const OTHER: [string, string][] = [
  ["character", "NPC / personagem"],
  ["vehicle", "Veículo"],
  ["tree", "Vegetação / árvore"],
  ["monument", "Monumento"],
  ["prop", "Objeto urbano"],
];
const MAX_PICS = 4;

export function CloudAgent({ onCreated }: { onCreated: (ids: string[], preview?: string | null) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [pics, setPics] = useState<Pic[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [category, setCategory] = useState("house");
  const [provider, setProvider] = useState("");
  const [iters, setIters] = useState<number | null>(null);
  const [target, setTarget] = useState<number | null>(null);
  const [polish, setPolish] = useState<PolishKey>("polished");
  const [stage, setStage] = useState(6);
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AiStatus>("/ai/status"), refetchInterval: 20000 });
  const s = status.data;

  const add = (files: Iterable<File>) => {
    const next: Pic[] = [];
    for (const f of files) {
      const e = checkImageFile(f);
      if (e) {
        setErr(`${f.name}: ${e}`);
        continue;
      }
      next.push({ key: `${f.name}-${f.size}-${Math.random()}`, file: f, url: URL.createObjectURL(f) });
    }
    setPics((p) => {
      const all = [...p, ...next];
      if (all.length > MAX_PICS) setErr(`no máximo ${MAX_PICS} imagens (vistas do mesmo prédio)`);
      return all.slice(0, MAX_PICS);
    });
  };
  const addRef = useRef(add);
  addRef.current = add;
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
        .map((it) => it.getAsFile())
        .filter((f): f is File => !!f)
        .map((f) => new File([f], `print-${Date.now()}.${f.type.split("/")[1] || "png"}`, { type: f.type }));
      if (files.length) {
        e.preventDefault();
        setErr(null);
        addRef.current(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  const go = useMutation({
    mutationFn: async () => {
      const ids: string[] = [];
      for (const p of pics) {
        const fd = new FormData();
        fd.append("file", p.file);
        const up = await fetch("/api/v1/references", { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
        const ref = await up.json().catch(() => ({}));
        if (!up.ok) throw new Error(typeof ref.detail === "string" ? ref.detail : `falha no upload (${up.status})`);
        ids.push(ref.id as string);
      }
      const pl = POLISH[polish];
      const label = CATEGORIES.find(([k]) => k === category)?.[1] ?? category;
      return api<{ id: string }>("/jobs", {
        method: "POST",
        json: {
          name: `${label} (agente IA)`,
          job_type: "agent.building",
          quality_profile: "stylized_detailed",
          formats: ["glb", "fbx", "blend"],
          params: {
            reference_ids: ids,
            category,
            provider: provider || undefined,
            construction_stage: stage,
            texture_resolution: pl.texture,
            wear: pl.wear,
            ...(iters !== null ? { max_iterations: iters } : {}),
            ...(target !== null ? { target_score: target } : {}),
          },
        },
      });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onCreated([r.id], pics[0]?.url ?? null);
    },
  });

  const blocked = !!s && (!s.configured || s.available === 0);
  return (
    <>
      <div className="st-title"><Bot size={16} /> Imagem → prédio (agente IA)</div>
      <div className="st-hint">
        A IA na nuvem (Gemini ou Grok) lê as referências e escreve a especificação completa; o kit monta em Blender, renderiza, a IA compara com as
        referências e corrige, até atingir a nota ou o limite de rodadas.
      </div>
      <label>Provedor<select value={provider} onChange={(e) => setProvider(e.target.value)}>
        <option value="">Pool automático</option><option value="gemini">Gemini</option><option value="grok">Grok</option>
      </select></label>
      {s && !s.configured && (
        <div className="st-warn">Nenhuma chave de API cadastrada. <Link to="/ai">Cadastre uma chave do Gemini</Link> (a chave fica só no servidor).</div>
      )}
      {s && s.configured && s.available === 0 && (
        <div className="st-warn">
          Todas as chaves estão no limite agora{s.next_available_at ? `; volta por volta de ${new Date(s.next_available_at).toLocaleString("pt-BR")}` : ""}. O pedido
          entra na fila e retoma sozinho quando a cota renovar.
        </div>
      )}

      <div className="dropzone small" role="button" tabIndex={0} aria-label="Escolher imagens de referência"
        onClick={() => input.current?.click()} onKeyDown={(e) => e.key === "Enter" && input.current?.click()}>
        {pics.length ? (
          <div className="drop-grid" onClick={(e) => e.stopPropagation()}>
            {pics.map((p) => (
              <div key={p.key} className="drop-item">
                <img src={p.url} alt="Referência" />
                <button className="icon x" aria-label="Remover imagem" onClick={() => setPics((all) => all.filter((x) => x.key !== p.key))}>
                  <X size={12} />
                </button>
              </div>
            ))}
            {pics.length < MAX_PICS && (
              <button className="drop-add" onClick={() => input.current?.click()} aria-label="Adicionar outra vista">
                <ImagePlus size={18} />
              </button>
            )}
          </div>
        ) : (
          <>
            <ImagePlus size={26} />
            <strong>Enviar ou colar 1 a {MAX_PICS} vistas do mesmo prédio</strong>
            <span>Clique, arraste ou use Ctrl+V · até {MAX_IMAGE_MB} MB cada</span>
          </>
        )}
        <input ref={input} type="file" multiple accept="image/png,image/jpeg,image/webp" hidden
          onChange={(e) => { if (e.target.files) { setErr(null); add(Array.from(e.target.files)); } e.target.value = ""; }} />
      </div>
      {err && <div className="check-fail">{err}</div>}

      <div className="st-fields">
        <label className="field" style={{ gridColumn: "1 / -1" }}>Tipo (dica para a IA)
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <optgroup label="Construções (kit procedural + IA)">
              {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </optgroup>
            <optgroup label="Outros — exigem o motor de reconstrução 3D (ainda não ligado ao painel)">
              {OTHER.map(([k, l]) => <option key={k} value={k} disabled>{l} (em breve)</option>)}
            </optgroup>
          </select>
          <span className="hint">NPCs, veículos, vegetação, monumentos e objetos urbanos serão gerados pelos motores de reconstrução (Pixal3D / TRELLIS.2), não por este agente de construções.</span>
        </label>
        <label className="field">Rodadas de correção
          <select value={iters ?? ""} onChange={(e) => setIters(e.target.value === "" ? null : Number(e.target.value))}>
            <option value="">Padrão ({s?.agent_iterations ?? 3})</option>
            {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label className="field">Nota alvo (0–10)
          <input type="number" min={0} max={10} step={0.5} placeholder={String(s?.target_score ?? 8)} value={target ?? ""}
            onChange={(e) => setTarget(e.target.value === "" ? null : Math.max(0, Math.min(10, Number(e.target.value))))} />
        </label>
        <label className="field">Acabamento
          <select value={polish} onChange={(e) => setPolish(e.target.value as PolishKey)}>
            {Object.entries(POLISH).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
          </select>
        </label>
        <label className="field">Estado de obra
          <select value={stage} onChange={(e) => setStage(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}{n === 6 ? " (pronto)" : ""}</option>)}
          </select>
        </label>
      </div>
      <div className="st-hint">
        Cada rodada usa 1 pedido à API (mais 1 para a especificação inicial). Imagens enviadas ao nível gratuito do Gemini podem ser usadas pelo Google
        para melhorar seus produtos.
      </div>
      <ErrorNote error={go.error} />
      <button className="st-generate" disabled={!pics.length || go.isPending || (!!s && !s.configured)} onClick={() => go.mutate()}>
        {go.isPending ? "Enviando…" : blocked && s?.configured ? "Enfileirar (aguarda a cota)" : "Gerar com o agente"}
      </button>
    </>
  );
}

interface Round {
  iteration: number;
  score: number;
  issues: string[];
  triangles: number;
  renders: string[];
}

/** Rounds of an agent job (scores, issues, renders), read from the asset's agent/history.json. */
export function AgentRounds({ url, fileUrlFor }: { url: string; fileUrlFor: (path: string) => string }) {
  const h = useQuery({
    queryKey: ["agent-history", url],
    queryFn: async () => {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`histórico indisponível (${r.status})`);
      return (await r.json()) as { best_score: number; target_score: number; rounds: Round[] };
    },
  });
  if (!h.data) return null;
  return (
    <div className="agent-rounds">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Agente IA</strong>
        <span className="chip">melhor nota {h.data.best_score.toFixed(1)} / 10 (alvo {h.data.target_score})</span>
      </div>
      {h.data.rounds.map((r) => (
        <details key={r.iteration} className="agent-round">
          <summary>Rodada {r.iteration + 1}: nota {r.score.toFixed(1)} · {r.triangles.toLocaleString("pt-BR")} triângulos</summary>
          <div className="agent-renders">
            {r.renders.map((p) => <img key={p} src={fileUrlFor(p)} alt={`Render da rodada ${r.iteration + 1}`} loading="lazy" />)}
          </div>
          {r.issues.length > 0 && <ul>{r.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>}
        </details>
      ))}
    </div>
  );
}
