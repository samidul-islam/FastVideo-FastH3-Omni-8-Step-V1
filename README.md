# FastVideo-FastH3-Omni-8-Step-V1 — AI Video SaaS (GPU Worker + Laravel + Flutter)

Bangladeshi AI video creation SaaS: text/image → video (with audio) via
**FastH3 Omni 8-step PDD** (MiniMax-H3 distilled), GPU worker on Vast.ai,
Laravel 11 backend on cPanel, Flutter app, bKash/Nagad payments.

## GPU decision (verified Oct 2026)

- **RTX PRO 6000 WS Blackwell (96 GB, sm_120)** — FastVideo `rtx-pro-6000`
  profile: 768p default, everything resident, no AdaLN table, no offloads.
- Model: `FastVideo/FastH3-OmniRef-NVFP4-QAD` (self-contained packed NVFP4
  export, ~69 GB — distilled transformer_ref + NVFP4 text encoder + VAEs).
- RTX 5090 rejected: AdaLN dump needs a separate GPU run, encoder offload,
  480p profile default, marginal cost advantage.
- BF16 checkpoint (`FastVideo-FastH3-Omni-8-Step-V1`) is for UniServe
  datacenter multi-GPU only — not for this deployment.

## Valid H3 buckets (only these)

- 768p: 1536×672, 1344×768, 1024×768, 768×768, 768×1024, 768×1344
- 480p: 992×416, 832×480, 640×480, 480×480, 480×640, 480×832
- Durations: 5s (124 frames) / 10s (243) / 15s (362), 24 fps, 32 kHz stereo audio
- No 720p/1080p, no 3:2/2:3, no 6–8s.

## Repository layout

```
worker/            FastAPI GPU worker (Docker)
  Dockerfile       CUDA 13 + torch 2.12 + fastvideo-kernel sm_120 + model bake
  handler.py       /health, /run, /status/{job_id} (X-Worker-Secret auth)
  requirements.txt worker app deps (FastVideo installed from git in Dockerfile)
  compose_model.py build-time model dir composer (symlinks, no GPU)
  test_input.json  sample /run payload (sync test mode)
docs/
  GUIDE-PHASE1.md  build / push / Vast.ai / test step-by-step (Bangla)
  ui-reference/    product UI design references (match in Phase 5/7)
```

## Phase status

- [x] Phase 1 — GPU worker (this commit): code complete, guide written.
      Build + Vast.ai deploy + smoke test = next (user-run, see GUIDE-PHASE1.md).
- [ ] Phase 2 — Laravel 11 cPanel + migrations (users/videos/payments/settings)
- [ ] Phase 3 — Laravel API (auth, generate, status, callback, payment, history)
- [ ] Phase 4 — Admin dashboard (Blade)
- [ ] Phase 5 — User frontend (Blade, design per docs/ui-reference)
- [ ] Phase 6 — Auto-delete scheduled command
- [ ] Phase 7 — Flutter app
- [ ] Phase 8 — bKash/Nagad
- [ ] Phase 9 — Launch
- [ ] Phase 10+ — new models (image gen, editing, series, upscaling, voice cloning)

## Build & deploy (Phase 1)

```bash
cd worker
docker build --build-arg HF_TOKEN=xxx -t <dockerhub-username>/fasth3-worker:latest .
docker push <dockerhub-username>/fasth3-worker:latest
# then: Vast.ai Serverless template — see docs/GUIDE-PHASE1.md
```
