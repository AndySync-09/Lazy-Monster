<p align="center">
  <img alt="The Lazy-Monster mascot" src="docs/assets/brand/mascot-animated.svg" width="170"><br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/wordmark-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/brand/wordmark-light.png">
    <img alt="Lazy-Monster" src="docs/assets/brand/wordmark-dark.png" width="420">
  </picture>
</p>

<h3 align="center">Say it. The monster does it. Now on Apple Silicon.</h3>

<p align="center">
  This is the <b>apple</b> branch: Lazy-Monster for Macs with M-series chips.<br>
  The Windows / Intel AI PC edition lives on <a href="https://github.com/AndySync-09/Lazy-Monster/tree/main"><b>main</b></a>.
</p>

<p align="center">
  <img alt="macOS 13+" src="https://img.shields.io/badge/macOS-13%2B-F3F1FF?style=for-the-badge&labelColor=0D0A1F">
  <img alt="Apple Silicon" src="https://img.shields.io/badge/Apple%20Silicon-M1%E2%80%93M4-C6F432?style=for-the-badge&labelColor=0D0A1F">
  <img alt="Works offline" src="https://img.shields.io/badge/offline-Brain--Break-F5C451?style=for-the-badge&labelColor=0D0A1F">
  <img alt="Status" src="https://img.shields.io/badge/status-preview-FF5FA2?style=for-the-badge&labelColor=0D0A1F">
</p>

## Install

One command in Terminal. No admin rights:

```bash
curl -fsSL https://raw.githubusercontent.com/AndySync-09/Lazy-Monster/apple/install.sh | bash
```

It asks for a brain (OpenAI, Claude, or a local model through Ollama, LM Studio or llama.cpp) and checks it, installs into `~/.lazymonster`, downloads the voice models, asks for Microphone, Accessibility and Automation access, learns your voice, sets up the quick brain, and starts at login. Push-to-talk: <kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd>.

Update by running the same command. Remove: `bash ~/.lazymonster/app/uninstall.sh`.

## Where it runs on a Mac

| Job | Runs on |
|---|---|
| Hearing what you said (Whisper, via MLX) | GPU |
| Quick brain for simple requests (Qwen2.5 1.5B, 4-bit, via MLX) | GPU |
| Reading text on your screen (Apple's Vision framework) | Neural Engine, where available |
| "Hey Monster" wake word, streaming captions | CPU |
| The monster's voice (Kokoro-82M), voice lock | CPU |

Apple Silicon shares one pool of memory between the CPU and GPU, so the quick brain and Whisper load fast and don't copy data around. Benchmark the quick brain on your Mac:

```bash
monster bench-brain --device MLX
```

## Same monster

Everything from main that isn't tied to Windows: real tasks in real apps (driven with AppleScript and Accessibility), Brain-Break offline mode, reminders that come to you, "why is my Mac slow?", "explain this error on my screen", the voice lock, conversation mode, the settings panel, skins and outfits. The safety rules are identical: no deleting, no shell, no sending, no buying, and it never closes itself.

Windows-only for now: the system-tray icon, the tray-only window style and desktop-pet mode.

## Preview status

This branch is newer than main and has had less real-world testing. Please open an issue with the output of `monster doctor` if anything misbehaves.

## License

[Apache 2.0](LICENSE). Bundled models keep their own licenses.
