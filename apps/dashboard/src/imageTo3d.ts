export const MAX_IMAGE_MB = 10;

/** Presets for a low/mid-poly game. `tris` is the LOD0 triangle target; the rest follows from it. */
export const PRESETS = {
  low: { label: "Low poly", hint: "props e itens", tris: 1500, profile: "prototype", tex: 512, lods: [0.5, 0.25] },
  mid: { label: "Mid poly", hint: "uso geral", tris: 6000, profile: "stylized_standard", tex: 1024, lods: [0.5, 0.25, 0.1] },
  high: { label: "Mid-alto", hint: "destaques", tris: 15000, profile: "stylized_detailed", tex: 2048, lods: [0.5, 0.25, 0.1] },
  custom: { label: "Custom", hint: "você define", tris: 3000, profile: "stylized_standard", tex: 1024, lods: [0.5, 0.25] },
} as const;
export type PresetKey = keyof typeof PRESETS;

export const PROVIDERS = {
  triposr: { title: "TripoSR", note: "MIT — uso comercial livre" },
  sf3d: { title: "Stable Fast 3D", note: "licença Stability: uso comercial exige registro" },
} as const;

export const STAGE_LABEL: Record<string, string> = {
  prepare: "Preparando as referências",
  conditioning: "Processando as imagens",
  inference: "Reconstruindo o modelo",
  surface: "Gerando a superfície e as texturas",
  image_to_3d: "Gerando a malha 3D a partir da imagem",
  postprocess: "Otimizando: reduzindo polígonos e gerando LODs",
  validate_outputs: "Validando o resultado",
  package: "Empacotando os arquivos",
  ai_spec: "A IA está lendo as referências e escrevendo a especificação",
  agent_loop: "Agente: renderizando, comparando com as referências e corrigindo",
  generate_geometry: "Montando a geometria",
  optimize: "Limpando a malha",
  validate_geometry: "Validando a geometria",
  textures: "Pintando as texturas",
  export: "Exportando (Blender)",
  thumbnail: "Renderizando a miniatura",
};

export function parseLods(text: string): number[] | null {
  const parts = text.split(/[,\s;]+/).filter(Boolean).map(Number);
  if (parts.some((n) => Number.isNaN(n) || n < 0.02 || n >= 1)) return null;
  return parts.every((n, i) => i === 0 || n < parts[i - 1]) ? parts : null;
}

/** Returns an error message when the file is not acceptable (checked before sending; the server checks again). */
export function checkImageFile(f: { type: string; size: number }): string | null {
  if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) return "use PNG, JPEG ou WEBP";
  if (f.size > MAX_IMAGE_MB * 1024 * 1024) return `maior que ${MAX_IMAGE_MB} MB`;
  return null;
}
