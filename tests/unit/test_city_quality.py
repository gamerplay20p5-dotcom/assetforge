import numpy as np

from scripts.engines.city_quality import compare, concerns


def test_intact_silhouette_does_not_hide_baking_or_surface_damage():
    master = np.zeros((64, 64, 4), dtype=np.float32)
    master[8:56, 8:56] = (0.7, 0.6, 0.4, 1)
    master[26:34, 35:45, :3] = 0.25
    clean, _ = concerns([compare(master, master, "vehicle")], 0, 0, 0)
    assert not clean

    damaged = master.copy()
    damaged[20:42, 12:34, :3] = 0
    damaged[37:44, 34:41, 3] = 0
    view = compare(master, damaged, "vehicle")
    assert view["silhouette_iou"] > 0.96
    assert view["interior_missing"] > 0
    assert "wheels" in view["regions"]
    issues, _ = concerns([view], 0.04, 0.2, 0)
    assert {"dark_patches", "color_mae", "surface_drift_p95", "projection_miss"} <= set(issues)
