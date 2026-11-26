"""Location of the script executed inside Blender (kept separate so importing it never imports bpy)."""

from pathlib import Path

RUNNER_PATH = Path(__file__).with_name("blender_runner.py")
