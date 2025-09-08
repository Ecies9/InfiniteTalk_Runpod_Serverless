# InfiniteTalk — Runpod Serverless Gradio UI

This UI provides a single-page app to submit jobs to your Runpod Serverless InfiniteTalk worker, monitor progress, and preview/download the generated video.

Key files:
- [Python.file app.py](InfiniteTalk_Runpod_Serverless/ui/app.py)
- [Python.file runpod_client.py](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py)
- [Python.file param_widgets.py](InfiniteTalk_Runpod_Serverless/ui/param_widgets.py)
- [Text.file requirements.txt](InfiniteTalk_Runpod_Serverless/ui/requirements.txt)
- [Text.file .env.example](InfiniteTalk_Runpod_Serverless/ui/.env.example)

References:
- Architecture: [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md)
- Guide: [Markdown.file GUIDE.md](GUIDE.md)
- Defaults: [YAML.file defaults.yaml](InfiniteTalk_Runpod_Serverless/config/defaults.yaml)
- Validator schema: [Python.file validator.py](InfiniteTalk_Runpod_Serverless/worker/validator.py)


## 1) Install

Python 3.10+ recommended.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r InfiniteTalk_Runpod_Serverless/ui/requirements.txt
```

Optionally copy env template and set your values:
```bash
cp InfiniteTalk_Runpod_Serverless/ui/.env.example InfiniteTalk_Runpod_Serverless/ui/.env
```

Then edit `.env` with your credentials:
- RUNPOD_API_KEY=...
- RUNPOD_ENDPOINT_ID=...


## 2) Run

Either run the script directly:
```bash
python InfiniteTalk_Runpod_Serverless/ui/app.py
```

Or from the `InfiniteTalk_Runpod_Serverless/ui` directory:
```bash
# From inside the ui/ folder
python -m app
```

Acceptance note: The UI is also import-safe to allow running via `python -m` forms; launching will start Gradio at `http://localhost:7860`.


## 3) Usage

- Inputs tab:
  - Enter Runpod API Key and Endpoint ID (persisted to `~/.config/infiniteTalk_ui/config.json` or local `./.ui_config.json`).
  - Choose input type:
    - image → talking head
    - video → dubbing/lip-sync
  - Provide either:
    - Reference Image (upload or URL), or
    - Reference Video (upload or URL)
  - Provide audio:
    - Upload/URL for person1 (required unless using TTS)
    - Optional person2 (if provided, choose audio_type para/add)
    - Or enable TTS and enter text (+ optional voices)
  - Prompt is required.

- Parameters tab:
  - Parameters mapped to the validator and defaults:
    - size, mode, frame_num, max_frame_num, sample_steps, sample_text_guide_scale, sample_audio_guide_scale, motion_frame, color_correction_strength
    - use_teacache (+ teacache_thresh), use_apg (+ apg_momentum, apg_norm_threshold)
    - base_seed, num_persistent_param_in_dit, offload_model
    - quant (+ quant_dir)
    - Output store selection: s3 | volume | inline
  - Values initialize from [YAML.file defaults.yaml](InfiniteTalk_Runpod_Serverless/config/defaults.yaml).

- Progress/Logs tab:
  - Live percent and stage based on Runpod status and worker checkpoints.
  - Structured logs are shown as timestamped JSON lines when provided.

- Output tab:
  - Final video displayed inline and a Download button if a local/temp file was created.
  - Artifacts and timings rendered as JSON.

- Submit:
  - The app calls Runpod `/run` async via [Python.function submit_job()](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py:1).
  - Polls `/status` via [Python.function get_status()](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py:1) with adaptive backoff per the architecture plan.


## 4) Behavior Details

- Input packaging:
  - Local files are encoded to base64 data URLs for portability and sent in the payload matching the worker schema described in [Markdown.file ARCHITECTURE.md](ARCHITECTURE.md).
  - If you prefer presigned uploads, provide URLs directly; the worker can download them.

- Polling cadence:
  - Starts at 2s interval, backs off up to 6s based on elapsed time.

- Error handling:
  - Worker error codes (E_*) are mapped to friendly messages with tips and a link to [GUIDE.md troubleshooting](InfiniteTalk_Runpod_Serverless/GUIDE.md#troubleshooting).

- Sanity checks:
  - Minimal checks: frame_num must be 4n+1, steps within [1, 1000], color correction in [0.0, 1.0], quant_dir required if quant is set.

- Batch:
  - Not implemented in this UI build (optional per scope). Single job submission is supported.


## 5) Screenshots (placeholders)

- Inputs/Parameters: TO ADD
- Progress/Logs: TO ADD
- Output: TO ADD


## 6) Development Notes

- UI blocks built in [Python.function build_ui()](InfiniteTalk_Runpod_Serverless/ui/app.py:1).
- Runpod client wrapper implements:
  - [Python.function submit_job()](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py:1)
  - [Python.function get_status()](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py:1)
  - [Python.function extract_progress()](InfiniteTalk_Runpod_Serverless/ui/runpod_client.py:1)
