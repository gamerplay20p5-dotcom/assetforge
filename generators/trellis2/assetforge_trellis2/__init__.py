"""AssetForge's TRELLIS.2 support code: a commercially usable texture bake (no nvdiffrast) and a guard that proves the non-commercial
libraries are never touched. Heavy modules (torch, cumesh) are imported lazily; import ``to_glb`` / ``uvraster`` only where they are used."""
