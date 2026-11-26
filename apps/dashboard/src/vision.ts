/** Fields of the house description the vision model fills (mirror of assetforge_vision.schema). Labels are shown to the user. */
export interface HouseDescription {
  floors: number;
  roof_type: string;
  roof_color: string;
  wall_material: string;
  wall_color: string;
  lower_wall_material: string;
  lower_wall_color: string;
  trim_color: string;
  door_color: string;
  door_position: string;
  windows_front_per_floor: number[];
  porch: string;
  garage: boolean;
  garage_side: string;
  chimney: boolean;
  volumes: string;
  bay_window: boolean;
}

export const DEFAULT_DESCRIPTION: HouseDescription = {
  floors: 2,
  roof_type: "gable",
  roof_color: "dark_gray",
  wall_material: "siding",
  wall_color: "beige",
  lower_wall_material: "none",
  lower_wall_color: "none",
  trim_color: "cream",
  door_color: "orange",
  door_position: "center",
  windows_front_per_floor: [2, 2],
  porch: "covered_porch",
  garage: false,
  garage_side: "none",
  chimney: false,
  volumes: "single",
  bay_window: false,
};

export const COLOR_HEX: Record<string, string> = {
  white: "#F4F1EA",
  cream: "#EEE4CE",
  beige: "#E2D2B0",
  tan: "#CDB48C",
  yellow: "#D9A85F",
  orange: "#C27A32",
  brown: "#6B4A32",
  red: "#B3392F",
  brick_red: "#A5503E",
  green: "#4C8A3E",
  sage_green: "#9DAD8E",
  dark_green: "#2D5B4A",
  blue: "#5E7798",
  gray_blue: "#6F86A0",
  gray: "#8A8D92",
  dark_gray: "#3A3D43",
  black: "#1F2125",
};
export const COLOR_LABEL: Record<string, string> = {
  white: "branco",
  cream: "creme",
  beige: "bege",
  tan: "areia",
  yellow: "amarelo",
  orange: "laranja",
  brown: "marrom",
  red: "vermelho",
  brick_red: "tijolo",
  green: "verde",
  sage_green: "verde-sálvia",
  dark_green: "verde escuro",
  blue: "azul",
  gray_blue: "azul acinzentado",
  gray: "cinza",
  dark_gray: "cinza escuro",
  black: "preto",
};
export const ROOF_TYPES: [string, string][] = [
  ["gable", "Duas águas"],
  ["hip", "Quatro águas"],
  ["shed", "Uma água"],
  ["flat", "Plano"],
];
export const WALL_MATERIALS: [string, string][] = [
  ["siding", "Tábuas"],
  ["brick", "Tijolo"],
  ["stucco", "Reboco"],
  ["stone", "Pedra"],
  ["wood", "Madeira"],
];
export const PORCHES: [string, string][] = [
  ["none", "Sem varanda"],
  ["covered_porch", "Varanda coberta"],
  ["portico", "Pórtico"],
  ["small_roof", "Marquise pequena"],
];
export const VOLUMES: [string, string][] = [
  ["single", "Bloco único"],
  ["l_shape", "Em L"],
  ["with_side_wing", "Com ala lateral"],
  ["stepped", "Em degraus"],
];
export const POSITIONS: [string, string][] = [
  ["left", "Esquerda"],
  ["center", "Centro"],
  ["right", "Direita"],
];

/** Finishing levels offered for the final model. Only what the generator really changes: texture size and wear of the paint. */
export const POLISH = {
  standard: { label: "Padrão", texture: 1024, wear: 0.12, hint: "textura 1024 px, leve desgaste de pintura" },
  polished: { label: "Polido", texture: 2048, wear: 0.03, hint: "textura 2048 px e pintura nova, sem desgaste" },
} as const;
export type PolishKey = keyof typeof POLISH;
