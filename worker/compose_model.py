"""Compose the FastH3 OmniRef NVFP4-QAD export into one model directory.

Mirrors compose_model_dir() from examples/inference/basic/basic_fasth3_omniref_pdd.py
in the FastVideo repo. The NVFP4-QAD export is self-contained — it ships the
distilled transformer_ref, the two schedulers, the packed NVFP4 text encoder,
processor, tokenizer and both VAEs — so the "base" snapshot is the export
itself.

Run at Docker build time (no GPU needed, pure symlinks):

    python compose_model.py /models/export /models/composed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTRACT = "fastvideo_inference.json"
EXPORT_COMPONENTS = ("transformer_ref", "scheduler", "audio_scheduler")
BASE_COMPONENTS = ("text_encoder", "tokenizer", "processor", "vae", "audio_vae")
MANIFESTS = ("modular_model_index.json", "model_index.json")
MANIFEST_COMPONENTS = ("scheduler", "audio_scheduler", *BASE_COMPONENTS)


def _link(destination: Path, source: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing checkpoint component: {source}")
    source = source.resolve()
    if destination.is_symlink():
        if destination.resolve() == source:
            return
        destination.unlink()
    elif destination.exists():
        raise FileExistsError(f"{destination} exists and is not a symlink")
    destination.symlink_to(source, target_is_directory=source.is_dir())


def _declares_components(manifest: Path) -> bool:
    """Whether a Diffusers manifest declares every component of the composed dir."""
    declared = {
        name
        for name, spec in json.loads(manifest.read_text(encoding="utf-8")).items()
        if isinstance(spec, list) and spec and spec[0] is not None
    }
    return set(MANIFEST_COMPONENTS) <= declared and bool({"transformer", "transformer_ref"} & declared)


def compose(export_dir: Path, composed_dir: Path) -> Path:
    export_dir = Path(export_dir)
    composed_dir = Path(composed_dir)
    composed_dir.mkdir(parents=True, exist_ok=True)

    # Distilled components + the PDD contract come from the export.
    for name in (*EXPORT_COMPONENTS, CONTRACT):
        _link(composed_dir / name, export_dir / name)

    # The export's manifest declares every component (it is self-contained).
    manifest_source = None
    for name in MANIFESTS:
        candidate = export_dir / name
        if candidate.is_file() and _declares_components(candidate):
            manifest_source = candidate
            break
    if manifest_source is None:
        raise FileNotFoundError(
            f"Export has no Diffusers manifest declaring {MANIFEST_COMPONENTS} and transformer_ref"
        )
    for name in MANIFESTS:
        stale = composed_dir / name
        if name != manifest_source.name and stale.is_symlink():
            stale.unlink()
    _link(composed_dir / manifest_source.name, manifest_source)

    # Shared base components (text encoder, tokenizer, processor, VAEs).
    for name in BASE_COMPONENTS:
        _link(composed_dir / name, export_dir / name)

    return composed_dir


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: compose_model.py <export-dir> <composed-dir>")
        raise SystemExit(2)
    out = compose(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Composed model directory: {out}")
