"""Compare consistently lit RGBA renders and record category-specific review areas."""

import numpy as np


REGIONS = {
    "building": {"doors": (0.45, 0.05, 0.58, 0.9), "windows": (0.05, 0.20, 0.95, 0.98)},
    "vehicle": {"wheels": (0.02, 0.02, 0.98, 0.40), "windows": (0.04, 0.38, 0.96, 0.93)},
    "npc": {"limbs": (0, 0, 1, 0.62), "arms": (0, 0.38, 1, 0.86)},
    "prop": {"edges": (0, 0, 1, 1)},
}


def _ratio(numerator, denominator):
    return float(numerator / max(1, denominator))


def _interior(mask):
    return (mask[1:-1, 1:-1] & mask[:-2, 1:-1] & mask[2:, 1:-1]
            & mask[1:-1, :-2] & mask[1:-1, 2:])


def _edges(rgb):
    value = rgb @ np.array([0.2126, 0.7152, 0.0722])
    return np.maximum(abs(value[1:-1, :-2] - value[1:-1, 2:]),
                      abs(value[:-2, 1:-1] - value[2:, 1:-1])) > 0.13


def compare(reference, candidate, category):
    source, target = reference[:, :, 3] > 0.5, candidate[:, :, 3] > 0.5
    shared = source & target
    rgb, other = reference[:, :, :3], candidate[:, :, :3]
    interior = _interior(shared)
    edges, other_edges = _edges(rgb), _edges(other)
    # A one-pixel tolerance keeps antialiasing and minor registration changes out of the detail score.
    shifted = np.lib.stride_tricks.sliding_window_view(np.pad(other_edges, 1), (3, 3))
    retained = shifted.any(axis=(-2, -1))
    bright, dark = rgb.mean(axis=2) > 0.22, other.mean(axis=2) < 0.055
    dark_patches = bright[1:-1, 1:-1] & _interior(dark)
    y, x = np.nonzero(source)
    regions = {}
    ys, xs = np.ogrid[:interior.shape[0], :interior.shape[1]]
    if x.size:
        for key, (x0, y0, x1, y1) in REGIONS[category].items():
            box = ((xs + 1 >= x.min() + x0 * np.ptp(x)) & (xs + 1 <= x.min() + x1 * np.ptp(x))
                   & (ys + 1 >= y.min() + y0 * np.ptp(y)) & (ys + 1 <= y.min() + y1 * np.ptp(y)))
            features = interior & edges & box
            regions[key] = {
                "edge_samples": int(features.sum()),
                "edge_recall": _ratio((features & retained).sum(), features.sum()) if features.any() else None,
                "silhouette_missing": _ratio((box & source[1:-1, 1:-1] & ~target[1:-1, 1:-1]).sum(),
                                             (box & source[1:-1, 1:-1]).sum()),
            }
    return {
        "silhouette_iou": _ratio(shared.sum(), (source | target).sum()),
        "interior_missing": _ratio((_interior(source) & ~target[1:-1, 1:-1]).sum(), _interior(source).sum()),
        "color_mae": float(np.abs(rgb - other)[shared].mean()) if shared.any() else 1.0,
        "dark_patches": _ratio((interior & dark_patches).sum(), interior.sum()),
        "new_edges": _ratio((interior & other_edges & ~edges).sum(), interior.sum()),
        "regions": regions,
    }


def concerns(views, surface_drift, projection_miss, level):
    # Provisional gates for the four matched views. Keep thresholds in the report for
    # audit and always leave window/door/wheel/limb semantics to visual review.
    limits = {
        "silhouette_iou": (0.96, 0.94, 0.92)[min(level, 2)],
        "interior_missing": 0.035, "color_mae": 0.10, "dark_patches": 0.012,
        "new_edges": 0.18, "surface_drift_p95": 0.030, "projection_miss": 0.12,
        "region_edge_recall": 0.46, "region_silhouette_missing": 0.10,
    }
    issues = {key for view in views for key in ("interior_missing", "color_mae", "dark_patches", "new_edges")
              if view[key] > limits[key]}
    if any(view["silhouette_iou"] < limits["silhouette_iou"] for view in views):
        issues.add("silhouette_iou")
    if surface_drift > limits["surface_drift_p95"]:
        issues.add("surface_drift_p95")
    if projection_miss is not None and projection_miss > limits["projection_miss"]:
        issues.add("projection_miss")
    if any(region["edge_samples"] >= 30 and region["edge_recall"] < limits["region_edge_recall"]
           or region["silhouette_missing"] > limits["region_silhouette_missing"]
           for view in views for region in view["regions"].values()):
        issues.add("regional_detail")
    return sorted(issues), limits
