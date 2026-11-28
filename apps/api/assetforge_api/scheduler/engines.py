"""Resource accounting for the experimental queue. Memory values are MiB."""

from datetime import timedelta
from math import ceil
from statistics import median

from assetforge_contract.engines import TEXT_REFERENCE
from sqlalchemy import or_, select

from ..models import Job, JobAttempt


def estimate(params: dict, unified: bool) -> dict:
    engine = params["engine"]
    category = params["category"]
    resolution = params["resolution"]
    density = max(0.5, resolution / 1024)
    detail = max(1.0, params["max_tokens"] / 49152) ** 0.45
    if params.get("skip_decimation"):
        detail *= 1.4
    texture = max(1.0, params["texture_size"] / 4096) ** 2
    baseline = {"npc": 4900, "building": 9300, "vehicle": 8900, "prop": 6400}[category]
    if engine == "pixal3d-python":
        return {"vram_mb": 0, "ram_mb": ceil(53000 * density**1.15 * max(1, texture**0.3)),
                "cpu_cores": 2, "expected_seconds": ceil(400 * density**2)}
    vram = ceil(baseline * density**1.65 * detail + (texture - 1) * 950)
    ram = ceil((vram * 1.3 + 4300) if unified else (2700 + vram * 0.60))
    seconds = ceil((90 if category == "npc" else 230) * density**2 * max(1, detail**0.4) * texture**0.15)
    if params.get("prompt"):
        ram = max(ram, 48000 if unified else 18000)
        vram = max(vram, 32000)
        seconds += 120
    return {"vram_mb": 0 if unified else vram, "ram_mb": ram, "cpu_cores": 1, "expected_seconds": seconds}


def estimate_reference(unified: bool) -> dict:
    return {"vram_mb": 0 if unified else 18000, "ram_mb": 48000 if unified else 18000,
            "cpu_cores": 1, "expected_seconds": 120}


def admission(db, job, worker, running: list[Job], now) -> tuple[dict | None, str | None]:
    sample = (worker.telemetry or {}).get("engine_gpu") or {}
    available = sample.get("ram_available_mb")
    total = sample.get("ram_total_mb")
    temp = sample.get("temperature_c")
    if (not worker.last_heartbeat or worker.last_heartbeat < now - timedelta(seconds=30)
            or type(available) is not int or type(total) is not int):
        return None, "aguardando telemetria do worker"
    if temp is None or temp >= 82:
        return None, "temperatura indisponível ou acima da margem térmica"
    unified = sample.get("unified") is True
    params = job.params
    reference = job.job_type == TEXT_REFERENCE
    need = estimate_reference(unified) if reference else estimate(params, unified)
    attempts = db.execute(
        select(JobAttempt, Job).join(Job, JobAttempt.job_id == Job.id)
        .where(JobAttempt.worker_id == worker.id, Job.job_type == job.job_type, Job.category == job.category,
               JobAttempt.finished_at.is_not(None))
        .order_by(JobAttempt.finished_at.desc()).limit(36)
    ).all()
    matched = [(attempt, previous) for attempt, previous in attempts
               if reference or (previous.params.get("engine") == params["engine"]
               and previous.params.get("resolution") == params["resolution"]
               and bool(previous.params.get("prompt")) == bool(params.get("prompt"))
               and bool(previous.params.get("skip_decimation")) == bool(params.get("skip_decimation"))
               and previous.params.get("max_tokens", 0) >= params["max_tokens"]
               and previous.params.get("texture_size", 0) >= params["texture_size"])]
    observed_seconds = []
    for attempt, previous in matched:
        if attempt.outcome == "succeeded":
            stats = (previous.result or {}).get("engine_runtime") or {}
            overlapping = db.scalar(select(JobAttempt.id).where(
                JobAttempt.id != attempt.id, JobAttempt.worker_id == worker.id,
                JobAttempt.started_at < attempt.finished_at,
                or_(JobAttempt.finished_at.is_(None), JobAttempt.finished_at > attempt.started_at),
            ).limit(1))
            # Host-wide deltas cannot describe a single job during overlapping runs.
            if overlapping is None:
                for resource, observed in (("ram_mb", "host_ram_delta_mb"), ("vram_mb", "gpu_delta_mb")):
                    if need[resource] and type(stats.get(observed)) is int:
                        need[resource] = max(need[resource], ceil(stats[observed] * 1.12))
            duration = max(1, ceil((attempt.finished_at - attempt.started_at).total_seconds()))
            observed_seconds.append(duration)
            need["expected_seconds"] = max(need["expected_seconds"], duration)
    if observed_seconds:
        need["historical_seconds"] = ceil(median(observed_seconds[:10]))
    failures = [attempt for attempt, _ in matched[:4] if attempt.outcome in {"failed", "abandoned"}]
    if failures and failures[0].finished_at >= now - timedelta(seconds=min(need["expected_seconds"], 300)):
        return None, "o motor está em recuperação após falha recente"
    recent_failures = sum(f.finished_at >= now - timedelta(minutes=30) for f in failures)
    if recent_failures:
        for resource in ("ram_mb", "vram_mb"):
            need[resource] = ceil(need[resource] * (1 + 0.15 * recent_failures))
    unseen = [j for j in running if j.started_at and j.started_at >= worker.last_heartbeat]

    def fits(resource, free, capacity, margin):
        if not all(type(x) is int for x in (free, capacity)):
            return False
        held = sum((j.requirements or {}).get(resource, 0) for j in running)
        pending = sum((j.requirements or {}).get(resource, 0) for j in unseen)
        return need[resource] <= min(free - pending, capacity - held) - margin

    if not fits("ram_mb", available, total, 12288 if unified else max(2048, total // 18)):
        return None, "reserva de RAM indisponível"
    if not unified:
        capacity = sample.get("vram_total_mb")
        free = sample.get("vram_free_mb")
        # Keep space for established services. Increased utilization adds margin
        # but does not impose a categorical concurrency limit.
        margin = max(2048, (capacity or 0) // 6)
        if (sample.get("utilization_percent") or 0) >= 95 and need["expected_seconds"] > 200:
            margin += 768
        if not fits("vram_mb", free, capacity, margin):
            return None, "reserva de VRAM indisponível"
    return {**job.requirements, **need}, None
