"""Makes the research/evaluation-only libraries unusable, so a run that finishes proves it never needed them.

nvdiffrast and nvdiffrec are under the NVIDIA Source Code License (1-Way Commercial: "research or evaluation purposes only"). TRELLIS.2 imports
nvdiffrast at module level in code the image->3D path never calls, so a plain import block would break unrelated imports. Instead the modules are
replaced by stubs that import fine and raise the moment anything is *used*. ``violations()`` lists every attempted use.
"""

from __future__ import annotations

import sys
import types

BLOCKED = ("nvdiffrast", "nvdiffrast.torch", "nvdiffrec_render", "nvdiffrec_render.light")
_attempts: list[str] = []


class _Stub(types.ModuleType):
    def __getattr__(self, name: str):  # noqa: ANN204
        if name.startswith("__"):
            raise AttributeError(name)
        _attempts.append(f"{self.__name__}.{name}")
        raise ImportError(f"{self.__name__}.{name}: this library is licensed for research/evaluation only and is blocked in commercial mode")


def block_noncommercial() -> None:
    """Call BEFORE importing trellis2 / o_voxel. Fails if a real copy was already imported."""
    for n in BLOCKED:
        mod = sys.modules.get(n)
        if mod is not None and not isinstance(mod, _Stub):
            raise RuntimeError(f"{n} was imported before the licence guard; start a fresh process")
    for n in BLOCKED:
        sys.modules[n] = _Stub(n)
    for n in BLOCKED:  # `import a.b as c` reads attribute b of a: link the stubs so importing works and only USING them raises
        if "." in n:
            parent, child = n.rsplit(".", 1)
            sys.modules[parent].__dict__[child] = sys.modules[n]


def violations() -> list[str]:
    return list(_attempts)
