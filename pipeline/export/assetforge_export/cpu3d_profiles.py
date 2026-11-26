"""Quality profiles for the CPU image-to-3D providers (STARTING values, to be calibrated with the benchmark on the real node).

Higher texture / marching-cubes resolution = better detail but much more CPU time and RAM. LOD0 triangles always follow the
asset contract budget (category x profile), applied by Blender decimation afterwards.
"""

from assetforge_contract import QualityProfile

CPU_PROFILES = {
    QualityProfile.prototype: {"texture": 512, "mc": 192},
    QualityProfile.stylized_standard: {"texture": 1024, "mc": 256},
    QualityProfile.stylized_detailed: {"texture": 2048, "mc": 320},
    QualityProfile.high_quality: {"texture": 2048, "mc": 384},
    QualityProfile.custom: {"texture": 1024, "mc": 256},
}
