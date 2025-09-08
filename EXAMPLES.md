# Examples — InfiniteTalk Runpod Serverless

Curated example payloads for common scenarios. These map to the schemas in [ARCHITECTURE.md](ARCHITECTURE.md). Use with /run (async) unless otherwise noted.

References:
- Generation core: `Python.function generate_infinitetalk()`
- Embedding extraction: `Python.function get_embedding()`
- Video muxing: `Python.function save_video_ffmpeg`


## Conventions

- Store outputs to S3 (recommended) with prefix infinitetalk/jobs.
- size defaults to infinitetalk-480; sample_steps 8–12 recommended for demos.
- For large inputs, host files externally or in a Runpod Network Volume and pass URLs/paths.

Result shape on success (abbreviated):
```json
{
  "job_id": "RP-abc123",
  "status": "success",
  "video": {
    "url": "https://s3.example.com/infinitetalk/jobs/RP-abc123.mp4",
    "mime": "video/mp4",
    "bytes": 12345678,
    "thumbnail_url": "https://s3.example.com/infinitetalk/jobs/RP-abc123.jpg"
  },
  "timings": { "total_ms": 133000 },
  "params": { "size": "infinitetalk-480", "sample_steps": 8 }
}
```


## 1) Single Image + Single Speaker (clip mode)

```json
{
  "input": {
    "prompt": "A woman sings in a studio",
    "cond_video": "https://example.com/media/image.jpg",
    "cond_audio": { "person1": "https://example.com/audio/voice.wav" },
    "size": "infinitetalk-480",
    "mode": "clip",
    "frame_num": 81,
    "sample_steps": 8,
    "sample_text_guide_scale": 1.0,
    "sample_audio_guide_scale": 2.0,
    "motion_frame": 9,
    "base_seed": 42,
    "output_config": { "store": "s3", "prefix": "infinitetalk/jobs" }
  }
}
```

Notes:
- Use high-quality portrait images; 3:4 to 9:16 aspect ratios yield best lip-sync framing.
- Expect ~0.5–2 min runtime on A100 for steps=8–12.


## 2) Single Video Dubbing + Single Speaker

```json
{
  "input": {
    "prompt": "A person speaking to camera",
    "cond_video": "https://example.com/media/input.mp4",
    "cond_audio": { "person1": "https://example.com/audio/clean.wav" },
    "size": "infinitetalk-480",
    "mode": "clip",
    "frame_num": 81,
    "sample_steps": 12,
    "motion_frame": 9,
    "sample_text_guide_scale": 1.0,
    "sample_audio_guide_scale": 2.0,
    "output_config": { "store": "s3", "prefix": "infinitetalk/jobs" }
  }
}
```

Notes:
- Worker auto-extracts audio features and muxes summarized audio into the output MP4.
- If the source video codec is AV1, it may be internally converted to H.264; ensure ffmpeg availability in the image.


## 3) Two Speakers (parallel), Single Image

```json
{
  "input": {
    "prompt": "Two people talking in a studio",
    "cond_video": "https://example.com/media/duo.jpg",
    "cond_audio": {
      "person1": "https://example.com/audio/s1.wav",
      "person2": "https://example.com/audio/s2.wav"
    },
    "audio_type": "para",
    "size": "infinitetalk-480",
    "mode": "clip",
    "frame_num": 81,
    "sample_steps": 10,
    "sample_text_guide_scale": 1.0,
    "sample_audio_guide_scale": 2.0,
    "output_config": { "store": "s3", "prefix": "infinitetalk/jobs" }
  }
}
```

Notes:
- audio_type=para mixes two streams in parallel (simultaneous overlap).
- For sequential turns, use audio_type=add (concatenation).


## 4) TTS-driven (single speaker)

```json
{
  "input": {
    "prompt": "A podcast host speaking",
    "cond_video": "https://example.com/media/host.jpg",
    "tts_audio": {
      "text": "Welcome to our show. Today we discuss emerging AI video.",
      "human1_voice": "weights/Kokoro-82M/voices/am_adam.pt"
    },
    "size": "infinitetalk-480",
    "mode": "clip",
    "frame_num": 81,
    "sample_steps": 8,
    "output_config": { "store": "s3", "prefix": "infinitetalk/jobs" }
  }
}
```

Notes:
- The worker generates TTS audio via Kokoro, then computes wav2vec2 embeddings and proceeds normally.
- Ensure voice tensors are present in the image or volume.


## 5) Long Video (streaming mode) — Single Speaker

```json
{
  "input": {
    "prompt": "A newsroom anchor delivering headlines",
    "cond_video": "https://example.com/media/anchor.mp4",
    "cond_audio": { "person1": "https://example.com/audio/anchor_long.wav" },
    "size": "infinitetalk-720",
    "mode": "streaming",
    "frame_num": 81,
    "max_frame_num": 1000,
    "motion_frame": 11,
    "sample_steps": 40,
    "use_teacache": true,
    "teacache_thresh": 0.2,
    "use_apg": true,
    "apg_momentum": -0.75,
    "apg_norm_threshold": 55,
    "num_persistent_param_in_dit": 0,
    "output_config": { "store": "s3", "prefix": "infinitetalk/stream" }
  },
  "policy": { "executionTimeout": 1800, "ttl": 86400 }
}
```

Notes:
- Use async /run; UI polls /status. Ensure executionTimeout covers end-to-end duration.
- 720p requires more VRAM; consider offload and VRAM management flags.


## 6) Batch Submission (two items)

```json
{
  "input": {
    "batch": [
      {
        "id": "item-1",
        "prompt": "A teacher explaining a concept",
        "cond_video": "https://example.com/media/teacher.jpg",
        "cond_audio": { "person1": "https://example.com/audio/t1.wav" },
        "size": "infinitetalk-480",
        "mode": "clip",
        "sample_steps": 8
      },
      {
        "id": "item-2",
        "prompt": "A chef presenting a recipe",
        "cond_video": "https://example.com/media/chef.jpg",
        "cond_audio": { "person1": "https://example.com/audio/c1.wav" },
        "size": "infinitetalk-480",
        "mode": "clip",
        "sample_steps": 12
      }
    ],
    "output_config": { "store": "s3", "prefix": "infinitetalk/batch" }
  }
}
```

Notes:
- Worker processes items sequentially on the same GPU; progress updates include item_id and item_index.
- Artifacts are named with job_id and per-item id suffix for clarity.


## Expected Output Characteristics

- Container/codec: H.264 in MP4, 25 fps.
- Resolution: derived from size bucket and input aspect ratio.
- Lip-sync quality depends on audio clarity and loudness normalization (handled internally via `Python.function loudness_norm()`).

## Troubleshooting Notes

- E_INPUT_VALIDATION: Ensure cond_video and at least one audio source (cond_audio or tts_audio).
- E_DOWNLOAD_FAILED: Host files on CDNs or ensure CORS and auth headers if needed.
- E_OOM: Reduce resolution to infinitetalk-480 and sample_steps to 8–12; keep concurrency=1.
- E_FFMPEG: Verify ffmpeg in the image and supported codecs in inputs.