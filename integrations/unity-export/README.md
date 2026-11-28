# AssetForge · Unity URP

1. Install the bundled `unity/Editor` and `unity/Runtime` scripts once in an URP project, under `Assets/AssetForgeIntegration/`. Keep the `Editor` directory name.
2. Extract each asset into its own directory under `Assets/`. Keep `model.fbx`, `assetforge-import.json`, `textures/` and, when present, `impostor/` together. The remaining GLB, BLEND and quality files can live outside Unity.
3. Select `assetforge-import.json` and run **Assets → AssetForge → Build URP prefab**. The editor writes `AssetForge.prefab` and the associated materials next to the FBX. Drag the prefab into a validation scene.
4. Inspect the LOD thresholds, scales, colliders and impostor frames in the target URP version. Material textures use sRGB for color, normal-map import for tangent normals and linear red-metallic/alpha-smoothness packing.

The decoder treats `relativeHeight` as Unity screen-relative height. The last mesh threshold is also the transition to the optional eight-view impostor. Atlas coordinates are pixels from the bottom left. Frames were rendered at 12° elevation and represent a frozen appearance for distant objects. Measure transitions and geometry budgets in the target Unity scene.
