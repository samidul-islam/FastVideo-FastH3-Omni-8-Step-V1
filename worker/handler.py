"""
FastH3 Omni GPU Worker — Phase 1
=================================

FastAPI service wrapping FastVideo's VideoGenerator for the
FastH3-OmniRef NVFP4-QAD checkpoint on one RTX PRO 6000 Blackwell (96 GB).

Device profile: ``rtx-pro-6000`` (sm_120, 768p, everything resident — no
AdaLN table, no text-encoder offload). 8-step PDD, 24 fps video + 32 kHz
stereo audio, output written as a single MP4 by the pipeline.

Endpoints
---------
GET  /health           GPU info, model status, supported resolutions/durations
GET  /status/{job_id}  Job state (queued / running / completed / failed)
POST /run              Generate a video. Requires X-Worker-Secret header.
    Body (JSON):
        prompt            required, text prompt (use <Picture 1> for i2v refs)
        duration          required, one of 5 / 10 / 15 seconds
        resolution        required, "768p" | "480p" (+ optional aspect_ratio)
                          or an exact "WxH" H3 bucket (e.g. "1344x768")
        mode              required, "t2v" | "i2v"
        aspect_ratio      optional, 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16 (default 16:9)
        image_base64      required when mode=i2v (PNG/JPEG, data-URI prefix ok)
        callback_url      optional; when set, the worker POSTs the finished
                          MP4 (multipart/form-data) to this URL with the
                          X-Worker-Secret header and /run returns immediately
        job_id            optional client-supplied id (auto-generated if absent)
        negative_prompt   optional, default ""
        seed              optional int, default 42

    - With callback_url  : returns {"job_id", "status": "queued"} immediately;
                           the worker calls back when the MP4 is ready
                           (or on failure, with status=failed and an error field).
    - Without callback_url : generates synchronously and returns the MP4 as
                           base64 (sync test mode).

Environment
-----------
WORKER_SECRET  Required. Shared secret checked against the X-Worker-Secret header.
MODEL_PATH     Composed model directory (default /models/composed).
PORT / HOST    Listen address (default 0.0.0.0:8080).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import io
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

from fastvideo import VideoGenerator
from fastvideo.api import (
    CompileConfig,
    ComponentConfig,
    EngineConfig,
    GenerationRequest,
    GeneratorConfig,
    InputConfig,
    OffloadConfig,
    OutputConfig,
    ParallelismConfig,
    PipelineSelection,
    QuantizationConfig,
    SamplingConfig,
)
from fastvideo.pipelines.basic.minimax_h3 import MiniMaxH3Reference

# ------------------------------------------------------------------ config
WORKER_SECRET = os.getenv("WORKER_SECRET", "")
MODEL_PATH = os.getenv("MODEL_PATH", "/models/composed")
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")
MODEL_LOAD_TIMEOUT = float(os.getenv("MODEL_LOAD_TIMEOUT", "1800"))  # seconds
CALLBACK_TIMEOUT = float(os.getenv("CALLBACK_TIMEOUT", "60"))
SYNC_MODE_TIMEOUT = float(os.getenv("SYNC_MODE_TIMEOUT", "1800"))

FPX = 24                          # MiniMax H3 video fps
NUM_INFERENCE_STEPS = 8           # PDD fused blocks (the contract's step count)
GUIDANCE_SCALE = 1.0
MAX_PROMPT_CHARS = 4000

WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp/worker"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("fasth3-worker")

# ------------------------------------------------------- H3 valid buckets
# Only these exact canvases exist in the H3 VAE bucket grid. Anything else
# (720p, 1080p, 3:2, 2:3, arbitrary WxH) must be rejected.
ASPECT_TO_SIZE: dict[int, dict[str, tuple[int, int]]] = {
    768: {
        "21:9": (1536, 672),
        "16:9": (1344, 768),
        "4:3": (1024, 768),
        "1:1": (768, 768),
        "3:4": (768, 1024),
        "9:16": (768, 1344),
    },
    480: {
        "21:9": (992, 416),
        "16:9": (832, 480),
        "4:3": (640, 480),
        "1:1": (480, 480),
        "3:4": (480, 640),
        "9:16": (480, 832),
    },
}
VALID_SIZES: set[tuple[int, int]] = {s for m in ASPECT_TO_SIZE.values() for s in m.values()}
DURATION_FRAMES: dict[int, int] = {5: 124, 10: 243, 15: 362}  # padded to 17n+5 at 24 fps


# ------------------------------------------------------------ model manager
class ModelManager:
    """Loads the VideoGenerator once, in a background thread."""

    def __init__(self) -> None:
        self._generator: Optional[VideoGenerator] = None
        self._ready = threading.Event()
        self._status = "idle"          # idle | loading | ready | error
        self._error: Optional[str] = None
        self._loaded_at: Optional[float] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._load, name="model-loader", daemon=True)
        self._thread.start()

    def _load(self) -> None:
        self._status = "loading"
        t0 = time.time()
        try:
            logger.info("Loading FastH3 Omni model from %s ...", MODEL_PATH)
            config = build_generator_config()
            self._generator = VideoGenerator.from_config(config)
            self._ready.set()
            self._loaded_at = time.time()
            self._status = "ready"
            logger.info("Model ready in %.1f s", time.time() - t0)
        except Exception as exc:  # noqa: BLE001
            self._status = "error"
            self._error = f"{type(exc).__name__}: {exc}"
            logger.exception("Model load failed")

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout)

    def generate(self, request: GenerationRequest) -> Any:
        if self._generator is None:
            raise RuntimeError("model not loaded")
        return self._generator.generate(request)

    def shutdown(self) -> None:
        if self._generator is not None:
            try:
                self._generator.shutdown()
            except Exception:  # noqa: BLE001
                logger.exception("generator.shutdown() failed")

    def status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "model_path": MODEL_PATH,
            "error": self._error,
            "loaded_at": self._loaded_at,
        }


def build_generator_config() -> GeneratorConfig:
    """rtx-pro-6000 device profile: NVFP4 DiT, everything resident."""
    return GeneratorConfig(
        model_path=MODEL_PATH,
        engine=EngineConfig(
            num_gpus=1,
            execution_backend="mp",
            use_fsdp_inference=False,
            parallelism=ParallelismConfig(tp_size=1, sp_size=1),
            offload=OffloadConfig(
                dit=False,
                dit_layerwise=False,
                text_encoder=False,
                vae=False,
                pin_cpu_memory=True,
                lazy_module_load=False,
            ),
            quantization=QuantizationConfig(
                transformer_quant="NVFP4",
                layer_profile="h3_dit_vsa",
            ),
            compile=CompileConfig(),
        ),
        pipeline=PipelineSelection(
            workload_type="i2v",
            components=ComponentConfig(
                override_pipeline_cls_name="MiniMaxH3Ref2VAModularPipeline",
            ),
            vae_tiling=True,
            experimental={
                "vae_parallel_decode": False,
                "vae_parallel_encode": False,
                "video_decode_backend": "h3-vae",
                "h3_sequential_load": False,
                "attention_backend": "VIDEO_SPARSE_ATTN_H3",
                "h3_vsa_fp4": {
                    "enabled": True,
                    "prefix_precision": "fp8",
                    "two_level_p": True,
                    "smooth_k": True,
                },
            },
        ),
    )


model = ModelManager()


# -------------------------------------------------------------------- jobs
@dataclass
class Job:
    job_id: str
    prompt: str = ""
    status: str = "queued"          # queued | running | completed | failed
    error: Optional[str] = None
    video_path: Optional[str] = None
    video_bytes: Optional[bytes] = None
    generation_time: Optional[float] = None
    peak_memory_mb: Optional[float] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class JobTask:
    job: Job
    prompt: str
    negative_prompt: str
    size: tuple[int, int]   # (width, height)
    frames: int
    ref_path: Optional[Path]
    callback_url: Optional[str]
    seed: int


jobs: dict[str, Job] = {}
job_queue: asyncio.Queue[JobTask] = asyncio.Queue(maxsize=32)


async def worker_loop() -> None:
    """Single consumer: one generation at a time on the one GPU."""
    while True:
        task = await job_queue.get()
        try:
            await process_job(task)
        except Exception:  # noqa: BLE001
            logger.exception("job loop crashed for %s", task.job.job_id)
            task.job.status = "failed"
            task.job.error = "internal worker error"
        finally:
            task.job.done.set()
            job_queue.task_done()


def run_generation(task: JobTask) -> Any:
    """Blocking generation call (runs in a worker thread)."""
    width, height = task.size
    references = []
    if task.ref_path is not None:
        references.append(MiniMaxH3Reference(source=str(task.ref_path), media_type="image"))
    output_path = WORK_DIR / f"{task.job.job_id}.mp4"
    request = GenerationRequest(
        prompt=task.prompt,
        negative_prompt=task.negative_prompt or "",
        inputs=InputConfig(references=references),
        sampling=SamplingConfig(
            height=height,
            width=width,
            num_frames=task.frames,
            fps=FPX,
            num_inference_steps=NUM_INFERENCE_STEPS,
            guidance_scale=GUIDANCE_SCALE,
            batch_cfg=False,
            seed=task.seed,
        ),
        output=OutputConfig(
            output_path=str(output_path),
            save_video=True,
            return_frames=False,
        ),
    )
    return model.generate(request)


async def process_job(task: JobTask) -> None:
    job = task.job
    job.status = "running"
    job.started_at = time.time()
    try:
        if not await asyncio.to_thread(model.wait_ready, MODEL_LOAD_TIMEOUT):
            raise RuntimeError("model did not finish loading within timeout")
        result = await asyncio.to_thread(run_generation, task)
        job.video_path = result.video_path
        job.video_bytes = Path(result.video_path).read_bytes()
        job.generation_time = result.generation_time
        job.peak_memory_mb = result.peak_memory_mb
        job.status = "completed"
        logger.info(
            "job %s completed: %s in %.1f s",
            job.job_id, result.video_path, (job.generation_time or 0.0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("job %s failed", job.job_id)
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = time.time()
        if task.ref_path is not None:
            try:
                task.ref_path.unlink(missing_ok=True)
            except OSError:
                pass
        if task.callback_url:
            await send_callback(task.callback_url, job, task.size, task.frames)


async def send_callback(callback_url: str, job: Job, size: tuple[int, int], frames: int) -> None:
    """Multipart POST the result (or the failure) to the PHP backend."""
    headers = {"X-Worker-Secret": WORKER_SECRET}
    fields: dict[str, str] = {"job_id": job.job_id, "status": job.status}
    files: Optional[dict[str, Any]] = None
    if job.status == "completed":
        fields.update(
            {
                "resolution": f"{size[0]}x{size[1]}",
                "duration_seconds": str(frames // FPX),
                "generation_time": f"{job.generation_time:.2f}" if job.generation_time is not None else "",
                "peak_memory_mb": f"{job.peak_memory_mb:.1f}" if job.peak_memory_mb is not None else "",
            }
        )
        files = {"video": (f"{job.job_id}.mp4", job.video_bytes, "video/mp4")}
    else:
        fields["error"] = (job.error or "unknown error")[:1000]

    ok = False
    for attempt in (1, 2, 3):
        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
                resp = await client.post(callback_url, headers=headers, files=files, data=fields)
            if 200 <= resp.status_code < 300:
                ok = True
                logger.info("callback for job %s accepted (HTTP %s)", job.job_id, resp.status_code)
                break
            logger.warning(
                "callback attempt %d for %s → HTTP %s: %s",
                attempt, job.job_id, resp.status_code, resp.text[:200],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("callback attempt %d for %s failed: %s", attempt, job.job_id, exc)
        await asyncio.sleep(5 * attempt)
    if not ok:
        logger.error("callback for job %s failed permanently (no more retries)", job.job_id)


# ----------------------------------------------------------------- helpers
def verify_secret(x_worker_secret: Optional[str]) -> None:
    if not WORKER_SECRET:
        raise HTTPException(status_code=500, detail="WORKER_SECRET not configured on worker")
    if not x_worker_secret or not hmac.compare_digest(x_worker_secret, WORKER_SECRET):
        raise HTTPException(status_code=401, detail="invalid or missing X-Worker-Secret header")


def resolve_canvas(resolution: str, aspect_ratio: Optional[str]) -> tuple[int, int]:
    """Validate and resolve the request canvas to an exact H3 bucket (W, H)."""
    r = (resolution or "").strip().lower()
    if r in ("768p", "480p"):
        short = 768 if r == "768p" else 480
        ar = (aspect_ratio or "16:9").strip()
        bucket = ASPECT_TO_SIZE[short]
        if ar not in bucket:
            raise HTTPException(
                status_code=400,
                detail=f"invalid aspect_ratio '{ar}' for {r}; valid: {sorted(bucket)}",
            )
        return bucket[ar]
    if "x" in r:
        try:
            w_s, h_s = r.split("x", 1)
            w, h = int(w_s), int(h_s)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid resolution '{resolution}'")
        if (w, h) not in VALID_SIZES:
            raise HTTPException(
                status_code=400,
                detail=f"resolution {w}x{h} is not a valid H3 bucket; valid sizes: {sorted(VALID_SIZES)}",
            )
        return (w, h)
    raise HTTPException(
        status_code=400,
        detail="invalid resolution; use '768p'/'480p' (+aspect_ratio) or an exact 'WxH' from the valid list",
    )


def save_image_ref(image_base64: str, job_id: str) -> Path:
    """Decode base64 image to a temp PNG for the reference encoder."""
    data = image_base64.strip()
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="image_base64 is not valid base64")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="image_base64 is not a valid image")
    path = WORK_DIR / f"{job_id}_ref.png"
    img.save(path, format="PNG")
    return path


def get_gpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {"available": False}
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,driver_version,compute_cap",
                "--format=csv,noheader",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    info.setdefault("gpus", []).append(
                        {
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total_mib": parts[2],
                            "memory_used_mib": parts[3],
                            "driver": parts[4],
                            "compute_capability": parts[5],
                        }
                    )
                    info["available"] = True
    except Exception:  # noqa: BLE001
        pass
    return info


def probe_mp4(path: str) -> dict[str, Any]:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(out.stdout)
        return {
            "duration_seconds": float(info["format"]["duration"]),
            "size_bytes": int(info["format"]["size"]),
        }
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------ schema
class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    duration: int
    resolution: str
    mode: str = "t2v"
    aspect_ratio: Optional[str] = None
    image_base64: Optional[str] = None
    callback_url: Optional[str] = None
    job_id: Optional[str] = None
    negative_prompt: str = ""
    seed: Optional[int] = None


# --------------------------------------------------------------------- app
app = FastAPI(title="FastH3 Omni Worker", version="1.0.0")


@app.on_event("startup")
async def startup() -> None:
    model.start()
    asyncio.create_task(worker_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    model.shutdown()


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "fasth3-omni-worker",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/health", "/run", "/status/{job_id}"],
    }


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "fasth3-omni-worker",
            "gpu": get_gpu_info(),
            "model": model.status(),
            "supported": {
                "resolutions": {
                    "768p": [f"{w}x{h}" for w, h in sorted(ASPECT_TO_SIZE[768].values())],
                    "480p": [f"{w}x{h}" for w, h in sorted(ASPECT_TO_SIZE[480].values())],
                },
                "aspect_ratios": sorted({ar for m in ASPECT_TO_SIZE.values() for ar in m}),
                "durations_seconds": sorted(DURATION_FRAMES),
                "frames_per_duration": DURATION_FRAMES,
                "fps": FPX,
                "num_inference_steps": NUM_INFERENCE_STEPS,
                "modes": ["t2v", "i2v"],
            },
        }
    )


@app.get("/status/{job_id}")
async def job_status(job_id: str, x_worker_secret: Optional[str] = Header(None)) -> dict[str, Any]:
    verify_secret(x_worker_secret)
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return {
        "job_id": job.job_id,
        "status": job.status,
        "error": job.error,
        "started_at": job.started_at or None,
        "finished_at": job.finished_at or None,
        "generation_time": job.generation_time,
    }


@app.post("/run")
async def run(req: RunRequest, x_worker_secret: Optional[str] = Header(None)) -> dict[str, Any]:
    verify_secret(x_worker_secret)

    if req.mode not in ("t2v", "i2v"):
        raise HTTPException(status_code=400, detail="mode must be 't2v' or 'i2v'")
    if req.duration not in DURATION_FRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"duration must be one of {sorted(DURATION_FRAMES)} seconds",
        )
    if req.mode == "i2v" and not req.image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required when mode=i2v")

    size = resolve_canvas(req.resolution, req.aspect_ratio)
    frames = DURATION_FRAMES[req.duration]
    prompt = req.prompt.strip()
    if req.mode == "i2v" and "<Picture" not in prompt:
        # Ref2VA prompts name their references; make the first image ref
        # explicit so the pipeline conditions on it.
        prompt = f"{prompt} <Picture 1>"

    job_id = (req.job_id or uuid.uuid4().hex).strip()
    if job_id in jobs:
        raise HTTPException(status_code=409, detail=f"job_id '{job_id}' already exists")
    seed = req.seed if req.seed is not None else 42

    ref_path = save_image_ref(req.image_base64, job_id) if req.mode == "i2v" else None
    job = Job(job_id=job_id, prompt=prompt)
    jobs[job_id] = job

    task = JobTask(
        job=job,
        prompt=prompt,
        negative_prompt=req.negative_prompt,
        size=size,
        frames=frames,
        ref_path=ref_path,
        callback_url=req.callback_url,
        seed=seed,
    )

    if req.callback_url:
        # Fire-and-forget: the worker calls back when the MP4 is ready.
        await job_queue.put(task)
        return {"job_id": job_id, "status": "queued", "callback_url": req.callback_url}

    # Sync test mode: wait for this job to finish, return base64.
    await job_queue.put(task)
    try:
        await asyncio.wait_for(job.done.wait(), timeout=SYNC_MODE_TIMEOUT)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="generation timed out")
    if job.status == "failed":
        raise HTTPException(status_code=500, detail=f"generation failed: {job.error}")

    probe = probe_mp4(job.video_path) if job.video_path else {}
    return {
        "job_id": job_id,
        "status": "completed",
        "video_base64": base64.b64encode(job.video_bytes).decode("ascii"),
        "video_size_bytes": len(job.video_bytes),
        "resolution": f"{size[0]}x{size[1]}",
        "duration_seconds": frames // FPX,
        "fps": FPX,
        "generation_time": job.generation_time,
        "peak_memory_mb": job.peak_memory_mb,
        **probe,
    }


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
