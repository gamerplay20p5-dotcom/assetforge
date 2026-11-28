import { portuguese, type Translate } from "./i18n";

/** Pure helpers (unit-tested with Vitest). */

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function timeAgo(iso: string | null | undefined, now: number = Date.now(), t: Translate = portuguese): string {
  if (!iso) return t("nunca");
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 5) return t("agora");
  if (s < 60) return t("{0}s atrás", s);
  if (s < 3600) return t("{0}min atrás", Math.floor(s / 60));
  if (s < 86400) return t("{0}h atrás", Math.floor(s / 3600));
  return t("{0}d atrás", Math.floor(s / 86400));
}

export interface BatchItem {
  name: string;
  quality_profile?: string;
  formats?: string[];
  priority?: number;
  params: Record<string, unknown>;
}

const NUMERIC = new Set(["seed", "width", "depth", "floors", "floor_height", "bay_width", "wear", "detail", "texture_resolution"]);
const BOOL = new Set(["balconies", "garage"]);

/** Split one CSV line honouring double quotes. */
export function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === "," || c === ";") {
      out.push(cur.trim());
      cur = "";
    } else cur += c;
  }
  out.push(cur.trim());
  return out;
}

/** CSV columns: name, category, style, seed, width, depth, floors, roof, wear, detail, formats (glb|blend|fbx),
 *  quality_profile, priority, count. A `count` > 1 expands the row into that many seeds. */
export function parseBatchCsv(text: string, t: Translate = portuguese): { items: BatchItem[]; errors: string[] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  const errors: string[] = [];
  if (lines.length < 2) return { items: [], errors: [t("CSV precisa de cabeçalho e ao menos uma linha")] };
  const header = splitCsvLine(lines[0]).map((h) => h.toLowerCase());
  const items: BatchItem[] = [];
  lines.slice(1).forEach((line, idx) => {
    const cells = splitCsvLine(line);
    const row: Record<string, string> = {};
    header.forEach((h, i) => (row[h] = cells[i] ?? ""));
    const lineNo = idx + 2;
    if (!row.name) {
      errors.push(t("linha {0}: 'name' é obrigatório", lineNo));
      return;
    }
    const params: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(row)) {
      if (v === "" || ["name", "quality_profile", "formats", "priority", "count"].includes(k)) continue;
      if (NUMERIC.has(k)) {
        const n = Number(v);
        if (Number.isNaN(n)) {
          errors.push(t("linha {0}: '{1}' não é número", lineNo, k));
          return;
        }
        params[k] = n;
      } else if (BOOL.has(k)) params[k] = ["1", "true", "sim", "yes"].includes(v.toLowerCase());
      else params[k] = v;
    }
    const count = Math.max(1, Math.min(1000, parseInt(row.count || "1", 10) || 1));
    for (let i = 0; i < count; i++) {
      const p = { ...params };
      if (count > 1) p.seed = Number(params.seed ?? 1) + i;
      items.push({
        name: count > 1 ? `${row.name} ${String(i + 1).padStart(3, "0")}` : row.name,
        ...(row.quality_profile ? { quality_profile: row.quality_profile } : {}),
        ...(row.formats ? { formats: row.formats.split("|").map((f) => f.trim()).filter(Boolean) } : {}),
        ...(row.priority ? { priority: Number(row.priority) } : {}),
        params: p,
      });
    }
  });
  return { items, errors };
}

export function parseBatchJson(text: string, t: Translate = portuguese): { items: BatchItem[]; errors: string[] } {
  try {
    const data = JSON.parse(text);
    const arr = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : null;
    if (!arr) return { items: [], errors: [t("JSON deve ser um array de itens ou { items: [...] }")] };
    const errors: string[] = [];
    const items: BatchItem[] = [];
    arr.forEach((it: Record<string, unknown>, i: number) => {
      if (typeof it !== "object" || it === null || typeof it.name !== "string") {
        errors.push(t("item {0}: 'name' é obrigatório", i + 1));
        return;
      }
      items.push({ ...(it as object), params: (it.params as Record<string, unknown>) ?? {} } as BatchItem);
    });
    return { items, errors };
  } catch (e) {
    return { items: [], errors: [t("JSON inválido: {0}", (e as Error).message)] };
  }
}

export function stateLabel(state: string, t: Translate = portuguese): string {
  const map: Record<string, string> = {
    queued: "Na fila",
    running: "Executando",
    succeeded: "Concluído",
    failed: "Falhou",
    cancelled: "Cancelado",
    scheduled: "Agendado",
    blocked: "Aguardando dependência",
    retrying: "Nova tentativa",
    cancelling: "Cancelando",
  };
  return t(map[state] ?? state);
}

export function stageLabel(stage: string | null, t: Translate = portuguese): string {
  const map: Record<string, string> = {
    prepare: "Preparar referências",
    conditioning: "Condicionar pelas imagens",
    inference: "Reconstruir geometria",
    surface: "Malha e texturas",
    generate_geometry: "Geometria",
    optimize: "Otimização",
    validate_geometry: "Validação de malha",
    textures: "Texturas",
    export: "Exportação",
    thumbnail: "Miniatura",
    validate_outputs: "Validação dos arquivos",
    package: "Pacote",
  };
  return stage ? t(map[stage] ?? stage) : "—";
}
