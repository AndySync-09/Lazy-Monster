# Lazy-Monster: architecture and milestones

## Decisions (locked)

| Area | Decision |
|---|---|
| Voice pipeline | **Hybrid.** Local wake phrase and instant commands. Realtime cloud model for conversation. Local TTS fallback offline |
| UI shell | **pywebview** (WebView2 on Windows) with an HTML/CSS/JS UI, all in one Python process |
| Wake phrase | **"Hey Monster"** (distinct sounds; far more robust across accents than the earlier "Hey Jev") |
| Planner | OpenAI Chat Completions with a forced `submit_plan` tool call. Jev API placeholder behind the same interface |
| Safety | Typed allowlist, local validation, local confirmation, sandboxed output. See `CLAUDE.md` invariants |
| License | Apache 2.0 |

## Current state (v0.6.0)

```
SLEEPING --wake word (NPU)--> LISTENING --end of turn--> THINKING --tool--> ACTING
    ^                                                         |              |
    |                                                         v              v
    +---- quiet, nothing pending ---- AWAITING <---- SPEAKING <--------------+
                                         |  your reply (any length) -> THINKING
```
- Every consumer (window, earcons, microphone gate, wake handling) reads `Conversation.state`.
- Turns: lines are joined until `turn_delay` of quiet; instant commands fire at once.

## Earlier state (v0.5.0)

- Wake word on the NPU (trained per user), idle gating of the CPU transcriber, barge-in, tray icon.
- Next (user's ranking): undo + routines + screen-injection guard; then MemFork memory + GPT-6 Astra escalation; then launch (benchmark vs the Jev demo, demo GIF, installer).

## Earlier state (v0.4.0)

- M1 UI shell done (`lazymonster/ui/`): particle monster, event bus, text box, Approve/Cancel, suggestions. Not yet: tray icon and settings page.
- Local speech: Moonshine streaming (pass 1) plus distil-Whisper on the NPU through OpenVINO GenAI (pass 2, agent requests only).
- Local voice: Kokoro-82M on the CPU (NPU needs static shapes; Kokoro's are dynamic). The realtime cloud voice (M2) is deferred: the user chose local voice.
- Platform split: `actions/windows.py` (full), `actions/posix.py` (first cut for macOS and Linux).

## Earlier state (v0.2.0)

- Agent loop (Chat Completions tool calling) replaces the one-shot planner: the model sees each tool result, including window contents via UI Automation, and continues until `finish`.
- Desktop tools: `list_windows`, `focus_window`, `read_window`, `click`, `type_text`, `press_keys`, all guarded in `guards.py`.
- Visible work: Word text streams into the document; code streams into files open in VS Code (`code_open`, `code_write_file`).
- NPU readiness: OpenVINO in the environment, `monster npu` detects and benchmarks NPU/GPU/CPU, `accelerator = auto` picks NPU first for on-device models. No model runs on the NPU yet; the first will be the wake word (M4).

## Previous state (v0.1.0)

- Instant lane with semantic endpointing: fires on a stable streaming partial. Compound requests and `open_app` wait for end of line.
- Agent lane: planner, then `generate_text`, `word_*`, `file_write_text`, `open_url`, plus all instant tools.
- CLI only: `run`, `text`, `plan`, `doctor`, `apps`, `bench-text`, `record`, `bench-audio`.
- Known issue from field testing: the old wake word "Jev" was misheard ("He gave", "Ages", "Egypt") under an Indian English accent. Hence "Hey Monster", plus M4.

## Target architecture

```
           ┌─────────────────────────── one Python process ───────────────────────────┐
 mic ──►   │ Moonshine STT (local) ─► wake "Hey Monster" ─► engine ─► instant grammar  │
           │                                      │                     │              │
           │                                      │ opens a session     ▼              │
           │  pywebview window (WebView2)         ▼               agent worker ─► apps │
           │  ┌──────────────────────────────────────────┐          ▲                  │
           │  │ orb · live transcript · plan cards       │  js_api  │ validated tools  │
           │  │ WebRTC ◄──► OpenAI Realtime (voice) ─────┼─────────►┘                  │
           │  └──────────────────────────────────────────┘                             │
           └───────────────────────────────────────────────────────────────────────────┘
```

- **Wake and instant commands stay local.** While a realtime session is open, mute the local transcriber (`MicTranscriber.mute(True)`) so the two don't fight over the mic.
- **The realtime session runs in the webview over WebRTC.** The browser's echo cancellation makes barge-in (interrupting the monster) work. Python mints a short-lived client secret; the long-lived API key never reaches JavaScript.
- **Realtime tool calls are forwarded to Python** through `window.pywebview.api`, validated with `validate()`, and executed on the worker. The result goes back as the function call output. Same allowlist, same confirmations.
- **Sessions close after about 20 s of silence** to keep cost down. "Hey Monster" reopens one.
- Model and endpoint names are configuration, not code. Check the current OpenAI Realtime docs when implementing M2; at the time of writing the WebSocket guide used `gpt-realtime-2.1`.

## Milestones for Claude Code

Each milestone ends with passing tests, `monster doctor` still green, and an updated `CHANGELOG.md`.

### M1: UI shell (pywebview)
- Frameless, always-on-top **orb window** (bottom-right) with states: idle, listening, thinking, speaking, needs-confirmation, error.
- **Live transcript** line and **plan card**: steps with status (pending, running, done, failed), plus **Approve** and **Cancel** buttons. Approve does exactly what a spoken "yes" does.
- **Tray icon** (pystray): open, pause listening, settings, quit.
- **Settings page:** model size, wake sensitivity (`stable_updates`), planner provider, API key status (set or not set; never the key), output folder.
- **Engine → UI event bus:** a thread-safe queue carrying JSON events. The UI never calls executors directly.
- Command: `monster ui`. `monster run` stays headless.
- Acceptance: all UI states demo-able in `--dry-run`, and no emojis; icons come from `docs/assets/icons`.

### M2: Realtime conversation voice
- `monster ui` opens a realtime session after "Hey Monster" when the grammar has no instant match.
- The session exposes the agent tools (from `intents.SCHEMA`) as realtime functions.
- Barge-in works. The transcript of both sides appears in the orb.
- Spoken confirmation ("yes") and the Approve button both resolve pending plans.
- Acceptance: "Hey Monster, open Word, write a short story about robots and save it" completes end-to-end by voice, with spoken progress.

### M3: Offline voice fallback
- Local TTS (moonshine-voice `tts` or a Kokoro-class model) for confirmations and short answers when offline or when `voice = "local"`.

### M4: Accent robustness and first NPU model
- `monster voice-train`: record about 30 minutes of guided prompts, then train a Moonshine LoRA adapter (`moonshine-voice[finetune]`). The adapter loads automatically.
- Dedicated wake-word model (openWakeWord-style, trained on "Hey Monster" with the user's samples), static input shapes, compiled with OpenVINO on `npu.select_device(cfg.accelerator)`, CPU fallback.
- Acceptance also includes idle CPU and package power, before and after moving the wake word to the NPU.
- Acceptance: `bench-audio` wake detection and command success improve on the user's recorded set, reported before and after.

### M5: More tools
- Excel (new workbook, write cells, save), PowerPoint (new deck from an outline, save), classic Outlook **draft only** (display, never send). All via COM on the worker thread, sandboxed saves, full tests.

### M6: Packaging and release
- PyInstaller one-folder build plus an Inno Setup installer with `docs/assets/brand/lazy-monster.ico`.
- GitHub Actions: tests on `windows-latest` for every PR; tagged releases attach the installer.
- Start-menu shortcut, optional start-with-Windows.

### M7: Real screenshots and demo
- Replace the illustrated setup images with real captures, and add a 20-second demo GIF of the orb doing the Word story task.
