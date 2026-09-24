# CLAUDE.md: working on Lazy-Monster

Lazy-Monster is a local-first voice agent for Windows: wake phrase "Hey Monster", on-device streaming speech recognition, an instant command grammar, and a planner that turns open-ended requests into typed, validated tool plans. Read `docs/SPEC.md` for the architecture and milestones before starting a milestone.

## Commands

All Python runs inside `.venv`. The CLI refuses to start outside it.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
```powershell
.\.venv\Scripts\monster.exe text
```
```powershell
.\.venv\Scripts\monster.exe run --dry-run -v
```
```powershell
.\.venv\Scripts\monster.exe do --dry-run open word and write a haiku
```

`text` is dry-run by default. Use `run --dry-run` whenever a change touches actions.

## Map

| Path | Role |
|---|---|
| `lazymonster/intents.py` | **The only list of things the app can do.** Typed schema, `validate()` |
| `lazymonster/grammar.py` | Instant lane: regex grammar → `Intent` |
| `lazymonster/engine.py` | Streaming callbacks, turn assembly (`poll`), semantic endpointing, confirmation, lane routing |
| `lazymonster/conversation.py` | **The single state machine**: UI state, mic gating, wake handling, earcons, acks. Add behaviour here, not as new flags |
| `lazymonster/sounds.py` | The three earcons (wake, done, error) |
| `lazymonster/service.py` | Background start at sign-in (HKCU Run + `monsterw.exe`), single instance |
| `lazymonster/userinfo.py` | First name from the Windows account, greetings |
| `lazymonster/journal.py` | Local journal of finished tasks: recaps, resume context |
| `lazymonster/savepaths.py` | "Save it as X on the desktop" parsing, default folder, allowed save roots |
| `lazymonster/platform_info.py` | `IS_WIN`, `IS_MAC`, `IS_APPLE_SILICON`: branch on these, not on `sys.platform` strings |
| `lazymonster/stt_sherpa.py` | Streaming speech on macOS (sherpa-onnx); same interface as the Moonshine mic |
| `lazymonster/actions/mac.py` | AppleScript and Accessibility helpers for the macOS executor (`actions/posix.py`) |
| `lazymonster/secrets.py` | API keys: environment, then the macOS Keychain |
| `lazymonster/voicelock.py` | Speaker verification (enroll, check); the engine's `verify` gate |
| `lazymonster/hotkey.py` | Global push-to-talk hotkey |
| `lazymonster/office_docs.py` | Documents built directly (PowerPoint from an outline), never by typing into the app |
| `lazymonster/agent.py` | Agent loop over Chat Completions tool calling; Jev placeholder client |
| `lazymonster/guards.py` | Runtime guards: blocked input targets, risky clicks, key allowlist, code paths |
| `lazymonster/npu.py` | OpenVINO device detection and `select_device()` for on-device models |
| `lazymonster/worker.py` | Single worker thread; runs instant plans and agent tasks; owns COM |
| `lazymonster/actions/` | `windows.py` (Win32 + dispatch), `uia.py` (UI Automation), `office.py` (Word COM), `code.py` (VS Code workspace), `files.py` (sandbox), `dryrun.py` |
| `lazymonster/stt.py` | Moonshine streaming speech recognition glue (pass 1) |
| `lazymonster/stt_refine.py` | Whisper on NPU via OpenVINO GenAI (pass 2), audio tap |
| `lazymonster/tts.py` | Voices: Kokoro (local, default), OpenAI, Windows |
| `lazymonster/textops.py` | Paste chunking, read-back verification, candidate parsing |
| `lazymonster/ui/` | pywebview window: `index.html` (particles, panel), `app.py` (event bus, API), `tray.py` |
| `lazymonster/wakeword.py` | NPU wake word: fixed-shape features, streaming, logistic head, detector |
| `lazymonster/wake_train.py` | `monster wake-train`: recordings + synthetic Kokoro data, training, threshold |
| `lazymonster/actions/posix.py` | macOS and Linux executor (first cut) |
| `docs/assets/` | Brand, icons and setup images. See Style |

## Invariants: never break these

1. **Every action is declared in `intents.SCHEMA`** with typed, range-checked slots. No tool may accept free-form commands.
2. **No shell, no delete, no send, no purchase, no credential access.** Never add a tool that runs a command line, `eval`s, deletes files, sends email or messages, or reads browser or password stores. The one exception is `code_run`/`code_install`: fixed interpreter, sandboxed project, only files the monster wrote (hash-checked), plain package names, and a spoken "yes" collected by the agent loop itself (`Agent.ASK_FIRST`). Do not widen it.
3. **Everything from a model goes through `validate()` and the agent's `AGENT_TOOLS` check.** That includes the agent, the realtime voice model and any future provider. Tools with `confirm` are never offered to a model.
4. **Confirmation and guards are decided locally** (`confirm` in the schema, `guards.py`). A model can never supply the "yes", type into a shell or VS Code, press banned shortcuts, or click irreversible controls. Extend `guards.py` rather than bypass it.
5. **Generated text is data.** Output of `generate_text` or a conversation may fill documents. It is never parsed back into tools.
6. **Files are written only under `Documents\LazyMonster`.** Documents are never overwritten; code projects under `Documents\LazyMonster\code\<project>` are agent workspaces and may be edited, through `safe_rel_path()` only.
7. **Keys come only from environment variables or Windows Credential Manager.** Never log them, write them to config or send them to the UI layer. The realtime voice session in the webview uses short-lived client secrets minted by Python.
8. **COM and Win32 calls run on the worker thread.**
9. **Instant-lane latency is a feature.** Don't add network calls, model calls or blocking I/O to `grammar.py` or `engine.on_partial`.
10. **The UI only displays and forwards.** `ui/index.html` never executes actions; its buttons send text through `Api.submit`, the same path as speech. Decision branches show what the agent reported, never invented data.

If a feature seems to need breaking an invariant, stop and write the trade-off in the PR description instead.

## Testing rules

- Every new tool needs tests for valid args, invalid types, out-of-range values, and a scripted agent run that uses it (see `ScriptedClient` in the tests).
- Engine behaviour is tested with the fake clock, synchronous `Worker` and `DryRunExecutor` (see `tests/test_engine.py`). No real audio, network or Windows in unit tests.
- Windows-only code is imported lazily so tests pass on CI runners.

## Style

- Python 3.11+, standard library first, type hints on public functions, no new dependency without a reason in the PR.
- **No emojis anywhere:** UI, docs, commit messages, logs or code comments. Use the SVG icon set in `docs/assets/icons/` (24px, 1.75 stroke, `#7C5CFF`) and extend it in the same style.
- Brand: ink `#0D1117`, monster violet `#7C5CFF` / `#5B3DE0`, lime `#C6F432`, text `#EDEFF5`, muted `#8A94A6`. Font: Space Grotesk; JetBrains Mono for code.
- Voice of the product: professional first, dry humour second. The monster is lazy about work, never about safety.
