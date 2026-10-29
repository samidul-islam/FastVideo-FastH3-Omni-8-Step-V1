# Phase 1 গাইড — GPU Worker (RTX PRO 6000 WS) — Build, Push, Vast.ai, Test

এই গাইড আপনার নিজের হাতে কাজ করার জন্য। প্রতিটি step আপনি নিজে run করুন।

---

## 1. GPU সিদ্ধান্ত: RTX PRO 6000 WS (মূলত RTX 5090 বাদ)

আমরা তিনটি লিংক চেক করেছি। সত্যিকার তথ্য কি:

| | RTX 5090 (32 GB) | RTX PRO 6000 WS (96 GB) |
|---|---|---|
| FastVideo ডিভাইস profile | `rtx-5090` — **480p ডিফল্ট**, text encoder offload, AdaLN table দিয়ে 26 GB এরিয়ে যায় | `rtx-pro-6000` — **768p ডিফল্ট**, encoder+DiT+decoder সব resident, **AdaLN table দরকার নেই** |
| Setup জটিলতা | AdaLN table dump (GPU চালাতে হয় একবার), NVFP4 VAE decoder swap, encoder প্রতি request offload | উপরে লিখিত সব কিছু Dockerfile এ বেক করা হয়েছে — অন্য কোনো manuel step নেই |
| BF16 checkpoint (`FastVideo-FastH3-Omni-8-Step-V1`) | 5090 এ চলে না — NVFP4-QAD variant লাগে | BF16 checkpoint এর জন্য UniServe runtime (8× GPU ভ্যালিডেটেড config) — আমরা NVFP4-QAD + FastVideo ব্যবহার করছি |
| Vast.ai প্রিসিং | ~$0.39/hr | ~$0.72–$1.73/hr (মিডিয়ান ~$1.64) |
| 5s ভিডিও তৈরির সময় (768p) | ~25s (NVFP4 benchmark) | ~25–35s (same sm_120 + NVFP4, 96 GB থাকায় আরামদায়ক) |
| প্রতি ভিডিও খরচ | ~0.3 BDT | ~1.7–3.3 BDT (২–৫ BDT budget এর মধ্যে) |

**কেন RTX PRO 6000 WS?** আপনি বলেছেন "কোন প্রকার সমস্যা যাতে না হয়"। RTX 5090 এ AdaLN table dump একটি আলাদা GPU run (FASTVIDEO_H3_ADALN_DUMP=1) দিয়ে তৈরি করতে হয় — Docker build time এ GPU নেই, তাই first-boot এ ঝুঁকি। PRO 6000 profile তে সেটা লাগে না (96 GB সব রেসিডেন্ট রাখতে পারে)। BF16 checkpoint এর UniServe path একাধিক GPU (8× RTX PRO 6000) দরকার — সেটা বাদ। NVFP4 numerics দুটো card এই একই।

RTX PRO 6000 **Max-Q** এর পরিবর্তে **WS** বেছে নেওয়ার কারণ: Max-Q হলো laptop/mobile variant (300W, 48GB) — Vast.ai এ desktop WS offer সুলভ্য, স্থিতিশীল।

---

## 2. Docker image build

Vast.ai build machine থেকে বা নিজ মেশিন থেকে run করুন:

```bash
cd worker

docker build \
  --build-arg HF_TOKEN=<your-hf-token> \
  -t <your-dockerhub-username>/fasth3-worker:latest .
```

- `HF_TOKEN`: HuggingFace token (optional — model প্রকাশ্য, কিন্তু rate limit এবং ভবিষ্যত gated model এর জন্য দিন)
- Build time: 25–45 min (kernel compile + 69 GB model download + flash-attn wheel)
- Build disk: আনুমানিক 120 GB+ (CUDA base + torch + 69 GB model + layers)
- Build RAM: 16 GB+ (CMake concurrency capped at 2)

> সমস্যা হলে: `--build-arg DOWNLOAD_MODELS=0` দিন → model first-boot এ নেমে আসবে।

## 3. Docker Hub push

```bash
docker login
docker push <your-dockerhub-username>/fasth3-worker:latest
```

## 4. Vast.ai Serverless configuration

1. vast.ai এ sign in → **Templates** → **New Template** (Serverless)
2. **Image**: `<your-dockerhub-username>/fasth3-worker:latest`
3. **GPU**: `RTX PRO 6000 WS` (Blackwell, 96 GB) — offer খুঁজতে `GPU family: RTX PRO 6000`, Sort by price। $0.72–$1.73/hr offer নিন।
4. **Container port**: `8080`
5. **Docker args**: `--shm-size=2g`
6. **Environment variables**:
   ```
   WORKER_SECRET=<random-32-char-secret>
   HF_TOKEN=<your-hf-token>
   PORT=8080
   ```
   `WORKER_SECRET` একটি strong random string তৈরি করুন — এটি পরে Laravel backend এ একই রাখতে হবে।
7. **Min workers**: `0`, **Max workers**: `1` (একটি GPU, একসময় একটি ভিডিও)
8. **Target Utilization**: `0.9`
9. **Request timeout**: `600` সেকেন্ড (model load + generation এর জন্য; Vast.ai এ "Timeout" setting এ দিন)
10. **Deploy** → template deploy করুন

> টিপস: Vast.ai serverless cold start এ model load হতে পারে 2–5 min। সেটি normal — backend এ callback এর জন্য wait করবে।

## 5. Test

### 5.1 /health

```bash
curl http://<worker-url>:8080/health
```

Expected: GPU name (RTX PRO 6000), model status `loading` → `ready`, valid resolutions/durations list।

### 5.2 /run sync test (base64 return)

```bash
curl -X POST http://<worker-url>:8080/run \
  -H "Content-Type: application/json" \
  -H "X-Worker-Secret: <WORKER_SECRET>" \
  -d @worker/test_input.json
```

Expected: `status: completed`, `video_base64` (768p 5s MP4)। এটি i2v টেস্ট নয় — t2v।

### 5.3 /run i2v test

```bash
curl -X POST http://<worker-url>:8080/run \
  -H "Content-Type: application/json" \
  -H "X-Worker-Secret: <WORKER_SECRET>" \
  -d '{
    "prompt": "A woman wearing <Picture 1> walks through a rainy street at night, neon lights",
    "duration": 5,
    "resolution": "480p",
    "aspect_ratio": "9:16",
    "mode": "i2v",
    "image_base64": "data:image/png;base64,iVBORw0KGgo...",
    "seed": 42
  }'
```

### 5.4 Callback test

```bash
curl -X POST http://<worker-url>:8080/run \
  -H "Content-Type: application/json" \
  -H "X-Worker-Secret: <WORKER_SECRET>" \
  -d '{
    "prompt": "A drone shot flying over a misty valley at dawn",
    "duration": 5,
    "resolution": "768p",
    "mode": "t2v",
    "callback_url": "https://your-laravel-domain/api/worker/callback"
  }'
```

Expected: `{"job_id": "...", "status": "queued"}` — তারপর ~1 min এ worker POST করবে multipart video + X-Worker-Secret header এ traceback এ। Phase 3 এ Laravel endpoint তৈরি করার পর এটি সম্পূর্ণ কাজ করবে।

## 6. খরচের হিসাব (per video)

| Duration | Resolution | Compute time | @ $1.64/hr | @ $0.72/hr |
|---|---|---|---|---|
| 5s | 768p 16:9 | ~30s | ~1.7 BDT | ~0.8 BDT |
| 10s | 768p 16:9 | ~50s | ~2.8 BDT | ~1.2 BDT |
| 5s | 480p | ~20s | ~1.1 BDT | ~0.5 BDT |

1 USD = 124.04 BDT। সবগুলো ২–৫ BDT budget এর মধ্যে।

## 7. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Build fails at kernel compile | `TORCH_CUDA_ARCH_LIST` must be `12.0a` (sm_120); CMake concurrency 2 এ রাখুন |
| `_uniserve_ipc` / protocol error | FastVideo version mismatch — Dockerfile এ `FASTVIDEO_REF=main` রেখেন |
| Model load error at boot | `DOWNLOAD_MODELS=0` থাকলে model নেই — first boot এ `hf download FastVideo/FastH3-OmniRef-NVFP4-QAD --local-dir /models/export` + compose run করুন |
| `FASTVIDEO_H3_ADALN_TABLE` error | AdaLN table rtx-pro-6000 profile এ লাগে না — handler এ দিয়ে দেখুন কোন env var overwrite করছে না |
| Out of memory at 768p 15s | সম্ভবত reference token বেশি — prompt shorten করুন বা 480p নিন |
| Callback timeout | Vast.ai request timeout 600s এ রাখুন; worker cold start + load + generation এর জন্য |
| Invalid resolution error | শুধু উপরের valid buckets ব্যবহার করুন (768p: 1536×672, 1344×768, 1024×768, 768×768, 768×1024, 768×1344; 480p: 992×416, 832×480, 640×480, 480×480, 480×640, 480×832) |

## 8. Phase 2 এর প্রস্তুতি

Phase 1 শেষ। Phase 2 তে Laravel 11 (PHP 8.4) cPanel setup + migrations (users/videos/payments/settings)। database config (cPanel MySQL) সেখানে দেওয়া হবে।
