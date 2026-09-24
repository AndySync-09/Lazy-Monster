# Voices and models: make the monster yours

Everything below runs on your PC. Change a setting with `monster voices`, the tray's **Open settings**, or by editing `%APPDATA%\lazymonster\settings.toml` (macOS: `~/.config/lazymonster/settings.toml`). Restart the monster afterwards: `monster service stop ; monster service start`.

## 1. Pick a speaking voice

```powershell
monster voices                      # list them
monster voices --play hf_alpha      # hear one
monster voices --use hf_alpha       # keep it
```

Built in: US, UK and Indian English voices from Kokoro-82M (Apache 2.0). You can also switch in the tray under **Voice**.

## 2. Bring your own speaking model

Any model in Kokoro's ONNX format works. Put the two files anywhere and point to them:

```toml
[lazymonster]
voice = "kokoro"
kokoro_model_path = "D:\\voices\\my-kokoro.onnx"
kokoro_voices_path = "D:\\voices\\my-voices.bin"
kokoro_voice = "my_voice_name"
```

Prefer a cloud voice? `voice = "openai"` with `tts_voice = "alloy"` (uses your OpenAI key). `voice = "windows"` uses the built-in Windows voices, `voice = "off"` keeps it silent.

## 3. Bring your own speech recognition

The accurate pass is Whisper. Use any OpenVINO Whisper export, either a Hugging Face repo id or a folder on disk:

```toml
stt_model = "OpenVINO/whisper-large-v3-int8-ov"      # a different repo
# or
stt_model = "D:\\models\\my-whisper-ov"                # your own export (optimum-cli export openvino ...)
stt_device = "GPU"                                    # NPU, GPU or CPU
```

On a Mac: `stt_model_mac_arm` (an MLX Whisper repo or folder) and `stt_model_mac_intel` (a faster-whisper model name or folder).

## 4. Your wake word and your voice lock

- `monster wake-train` retrains "Hey Monster" on your voice (your accent, your mic, your room). Re-run it if you move somewhere noisier or change microphones.
- `monster wake-test` shows a live score while you say it; `wake_sensitivity = 0.1` if it misses you, `-0.1` if it wakes by itself.
- `monster voice-enroll` records your voiceprint for the voice lock; `monster voice-test` checks it; `monster voice-lock off` turns it off.

## 5. The brain, and Jev

The brain writes and plans: OpenAI or Claude, chosen during install. Change it later:

```toml
planner = "anthropic"                         # openai | anthropic | local
go_big = true                                 # hard tasks on the stronger model
anthropic_model = "claude-haiku-4-5-20251001"
anthropic_escalation_model = "claude-sonnet-5"
```

**Local models.** Ollama, llama.cpp (`llama-server --jinja`), vLLM (`--enable-auto-tool-choice`) or LM Studio:

```toml
planner = "local"
local_base_url = "http://localhost:11434/v1"
local_model = "qwen3:8b"                      # must support tool calling
```

With a local brain, web research searches DuckDuckGo, or Brave Search if you set `BRAVE_API_KEY`, and summarises the pages locally.

**Jev** (TypeSafe) is optional and works next to the brain. It doesn't write text; it answers typed questions (yes/no, a choice, a score) in milliseconds. The monster uses it to decide whether speech without a wake word was meant for it, which tool fits a request (the decision tree shows Jev's real probabilities), whether a task is hard enough to start on the stronger model, and whether "sure, go for it" means yes. If Jev is slow or unreachable, the monster simply carries on without it.

```toml
decider = "jev"                               # "" to turn it off
jev_model = "jev-latest"                      # key: TYPESAFE_API_KEY (console.typesafe.ai)
```
