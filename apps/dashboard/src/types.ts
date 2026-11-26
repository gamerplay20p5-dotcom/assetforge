export interface Job {
  id: string;
  batch_id: string | null;
  asset_id: string;
  name: string;
  job_type: string;
  category: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  state: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  worker_id: string | null;
  progress: number;
  current_stage: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  not_before: string | null;
  depends_on: string[];
  tags: string[];
  formats: string[];
  quality_profile: string;
  cancel_requested: boolean;
  asset_version: number | null;
  retry_of: string | null;
  seed: number | null;
  eta_seconds: number | null;
  params?: Record<string, unknown>;
  plan?: { name: string; weight: number }[];
  stages?: Record<string, { status: string; started_at?: string; finished_at?: string; detail?: string }>;
  attempt_history?: { attempt: number; worker_id: string | null; started_at: string; finished_at: string | null; outcome: string; error: string | null }[];
  result?: Record<string, unknown> | null;
}

export interface JobLog {
  id: number;
  ts: string;
  attempt: number;
  level: string;
  source: string;
  message: string;
}

export interface Batch {
  id: string;
  name: string;
  created_at: string;
  created_by: string;
  total: number;
  counts: Record<string, number>;
  finished: number;
  progress: number;
}

export interface Gpu {
  vendor?: string;
  name: string;
  kind?: string;
  vram_total_mb?: number | null;
  vram_used_mb?: number | null;
  utilization_percent?: number | null;
  temperature_c?: number | null;
  source?: string;
}

export interface Worker {
  id: string;
  name: string;
  kind: string;
  address: string;
  hostname: string;
  version: string;
  state: "enabled" | "disabled" | "maintenance";
  online: boolean;
  status: string;
  last_heartbeat: string | null;
  registered_at: string;
  capabilities: {
    features?: string[];
    blender_version?: string | null;
    formats?: string[];
    os?: string;
    cpu_model?: string;
    cpu_cores_total?: number;
    ram_total_mb?: number;
    gpus?: Gpu[];
    models?: { name: string }[];
    ai_runtimes?: { openvino?: string | null; torch?: string | null; validated?: string[] };
    schedule?: { active_hours?: string; max_host_cpu_percent?: number; yield_to?: string[] };
  };
  limits: { max_concurrent_jobs?: number; cpu_cores?: number; ram_mb?: number; vram_mb?: number };
  telemetry: {
    cpu_percent?: number;
    ram_used_mb?: number;
    ram_total_mb?: number;
    temperature_c?: number | null;
    gpus?: Gpu[];
    gate?: string | null;
  };
  active_jobs: number;
  jobs_succeeded: number;
  jobs_failed: number;
  recent_jobs?: { id: string; name: string; status: string; progress: number; finished_at: string | null }[];
}

export interface FileEntry {
  name: string;
  role: string;
  format: string;
  size: number;
  sha256: string;
}

export interface Asset {
  id: string;
  name: string;
  category: string;
  tags: string[];
  favorite: boolean;
  review_status: "pending" | "approved" | "rejected";
  current_version: number;
  art_profile: string;
  generator_id: string;
  created_at: string;
  updated_at: string;
  triangle_count: number;
  engine: string;
  dimensions_m: [number, number, number] | null;
  seed: number | null;
  version_count: number;
  has_thumbnail: boolean;
  validation_passed: boolean;
  files?: FileEntry[];
  manifest?: Manifest;
  validation?: { passed: boolean; checks: { name: string; status: string; detail: string }[]; metrics: Record<string, unknown> };
  version_info?: { version: number; job_id: string | null; note: string; created_at: string };
  versions?: { version: number; job_id: string | null; triangle_count: number; engine: string; created_at: string; note: string }[];
}

export interface Manifest {
  materials: { name: string; base_color: string; texture: string | null; roughness: number; metallic: number }[];
  textures: string[];
  lods: { level: number; triangles: number; file: string }[];
  colliders: { type: string; center: number[]; size: number[] }[];
  connection_points: { name: string; position: number[] }[];
  triangle_budget: [number, number];
  triangle_count: number;
  bounding_box: [number[], number[]];
  generation_params: Record<string, unknown>;
  provenance: Record<string, string>;
  license: string;
  generator_id: string;
  generator_version: string;
  quality_profile: string;
}

export interface Summary {
  jobs: { running: number; queued: number; succeeded: number; failed: number; cancelled: number; paused: boolean };
  assets: { total: number; by_review: Record<string, number> };
  workers: { total: number; online: number; busy: number };
  resources: {
    cpu_percent: number | null;
    ram_used_mb: number | null;
    ram_total_mb: number | null;
    gpu_percent: number | null;
    vram_used_mb: number | null;
    vram_total_mb: number | null;
    gpu_count: number;
  };
  storage: { total_bytes: number; free_bytes: number; assets_bytes: number };
  history: { hour: string; succeeded: number; failed: number; cancelled: number }[];
  avg_job_seconds: number | null;
}

export interface GeneratorInfo {
  id: string;
  version: string;
  categories: string[];
  palettes: Record<string, string[]>;
  budgets: Record<string, [number, number]>;
  quality_profiles: Record<string, number>;
}

export interface Preset {
  id: string;
  name: string;
  data: Record<string, unknown>;
}
