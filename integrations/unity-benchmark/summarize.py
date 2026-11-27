"""Summarize measurements emitted by the real Unity player."""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    environment = (args.results / "environment.txt").read_text(encoding="utf-8").splitlines()
    if len(environment) != 5 or environment[2].lower() == "null":
        raise ValueError("Missing Unity graphics run metadata")
    scenarios = defaultdict(list)
    with (args.results / "frames.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            scenarios[row["scenario"]].append(row)
    if not scenarios:
        raise ValueError("The Unity benchmark produced no frame samples")
    report = {}
    for scenario, rows in scenarios.items():
        times = sorted(float(r["frame_ms"]) for r in rows)
        if min(times) <= 0:
            raise ValueError(f"Invalid frame time in {scenario}")
        samples = {
            "frames": len(times), "fps": 1000 / statistics.mean(times),
            "p50_frame_ms": statistics.median(times), "p95_frame_ms": times[math.ceil(0.95 * len(times)) - 1],
            "visible_lod_switches": sum(int(r["visible_lod_switches"]) for r in rows),
        }
        for name in ("draw_calls", "rendered_triangles", "used_bytes"):
            values = [int(r[name]) for r in rows if r[name] != ""]
            samples[f"peak_{name}"] = max(values, default=None)
        report[scenario] = samples
    print(json.dumps({"environment": environment, "scenarios": report}, indent=2))


if __name__ == "__main__":
    main()
