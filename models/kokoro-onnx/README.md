# Kokoro-ONNX Models

This directory should contain the Kokoro-ONNX model files for local voice cloning.

## Required Files

| File | Size | Description |
|------|------|-------------|
| `kokoro-v1.0.onnx` | ~308 MB | Main acoustic model |
| `voices-v1.0.bin` | ~56 MB | Voice embeddings / speaker database |

**Alternative naming (also supported):**
- `model.onnx` + `voices.bin`

## Automatic Download

Run the download script:

```bash
# From project root
python scripts/download_kokoro_model.py

# Or with custom directory
python scripts/download_kokoro_model.py --model-dir models/kokoro-onnx

# Force re-download
python scripts/download_kokoro_model.py --force

# Use fallback (GitHub releases)
python scripts/download_kokoro_model.py --fallback
```

The script supports:
- ✅ Resume interrupted downloads
- ✅ Parallel downloads (3 workers by default)
- ✅ Progress bars
- ✅ Automatic fallback to GitHub releases
- ✅ Size verification

## Manual Download

If automatic download fails, manually download from:

### Primary (Hugging Face)
- https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v1.0.onnx
- https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices-v1.0.bin

### Fallback (GitHub Releases)
- https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.1.0/kokoro-v1.0.onnx
- https://github.com/thewh1teagle/kokoro-onnx/releases/download/v0.1.0/voices-v1.0.bin

Place both files in this directory.

## Verification

Check models are correctly placed:

```bash
ls -la models/kokoro-onnx/
# Should show:
# kokoro-v1.0.onnx  (~308 MB)
# voices-v1.0.bin   (~56 MB)
```

Run verification:
```bash
python scripts/download_kokoro_model.py --verify-only
```

## Mock Mode

If models are not available, the system runs in **mock mode**:
- Voice cloning API returns mock audio files (empty .wav)
- Voice print creation still works (stores metadata)
- All other functionality remains operational
- Logs show: `⚠️ Kokoro models not available - returning MOCK audio`

This allows development/testing without the large model files.

## CI/CD Integration

For CI pipelines, add to your workflow:

```yaml
- name: Download Kokoro Models
  run: |
    python scripts/download_kokoro_model.py --model-dir models/kokoro-onnx
    # Or cache the models directory between runs
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `NameResolutionError` | Network/DNS blocked. Use manual download or configure proxy. |
| `SSL Certificate Error` | Try `--fallback` for GitHub releases, or update certifi. |
| `Size mismatch` | Re-run with `--force` to re-download corrupted files. |
| `Permission denied` | Ensure write permissions on models directory. |

## Model Info

- **Model**: Kokoro-82M (82M parameters)
- **Format**: ONNX (optimized for CPU inference)
- **Languages**: Chinese, English, Japanese, Korean, etc.
- **Voices**: 100+ pre-trained voices in voices.bin
- **License**: Apache 2.0 (check HF repo for details)

## References

- [Kokoro-ONNX GitHub](https://github.com/thewh1teagle/kokoro-onnx)
- [Hugging Face Model Card](https://huggingface.co/hexgrad/Kokoro-82M)
- [Original Kokoro Paper](https://arxiv.org/abs/2406.06696)
