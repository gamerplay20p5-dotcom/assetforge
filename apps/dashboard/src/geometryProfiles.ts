export const geometryProfiles = {
  master: { label: "Master integral", ratio: 1 },
  high: { label: "High Poly", ratio: 0.8 },
  mid: { label: "Mid Poly", ratio: 0.45 },
  low: { label: "Low Poly", ratio: 0.15 },
} as const;

export type GeometryProfile = keyof typeof geometryProfiles;

export function geometryProfile(value: string | null): GeometryProfile {
  return value && Object.hasOwn(geometryProfiles, value) ? value as GeometryProfile : "master";
}
