# Security

Lazy-Monster controls a real computer from a microphone. We treat that seriously.

## The model

- **Typed allowlist.** Every action is declared in `lazymonster/intents.py` with typed, range-checked arguments. Requests for anything else are rejected, whoever makes them (grammar, planner or realtime voice model).
- **No dangerous tools exist.** There is no shell, file deletion, email sending, purchasing, or access to passwords or browser data.
- **Guarded desktop control.** The agent can read windows, click, type and press keys, so these are guarded locally: no input into terminals, VS Code, credential or security prompts, Task Manager or Settings; no shortcuts that open a run box or shell; no clicks on controls named like delete, send, pay, buy, install or uninstall. Code goes to files inside `Documents\LazyMonster\code`, never typed into an editor.
- **Sensitive windows and ownership.** Windows whose titles suggest secrets (passwords, recovery codes, keys, tokens, `.env`, wallets, banking) are never typed into, clicked in or read, and their titles are redacted before anything reaches a model. The monster only edits new documents or documents you named.
- **Running code.** The monster can run Python files it wrote in `Documents\LazyMonster\code`, and install packages into that project's own environment, only after you say yes each time. It refuses files it did not write or that changed since. Code it runs has your permissions: read what it wrote in VS Code before saying yes if the task came from untrusted content.
- **Background listening.** In background mode the microphone is open from sign-in so the wake word can hear you. Until "Hey Monster", audio only reaches the on-device wake-word model on the NPU; nothing is transcribed, stored or sent. Quit from the tray or with `monster service stop`.
- **Closing and saving.** "Close everything" only touches what the monster opened this session, and only the Notepad tab it wrote in. Unsaved work is never discarded without your "no". Saves go to the name and place you say (limited to your default save folder and your own profile folders) or to `default_save_dir`.
- **Journal.** Finished tasks and file paths are kept locally in `journal.jsonl` for recaps. Delete the file to forget.
- **Opening files.** `open_file` opens documents and media only (HTML, PDF, Office files, text, images, audio/video), from your own folders or the default save folder. Programs and scripts are never opened this way.
- **Web research** sends your research question to the configured OpenAI endpoint, which searches the web. Harder tasks may be sent to `escalation_model` (set it to "" to never use a second model).
- **Voice lock.** Once you enroll, spoken requests are only carried out if they match your voiceprint (stored locally in `%LOCALAPPDATA%\\lazymonster\\models\\voicelock`). Voice matching is strong against other people and recordings of other people, but not proof against a recording of your own voice; risky actions still need your spoken "yes".
- **macOS permissions.** On a Mac it needs Microphone, Accessibility (click and type), Automation (drive apps) and Input Monitoring (hotkey). The same guards apply: blocked apps include Terminal, iTerm, Keychain Access and System Settings. The API key is stored in your login Keychain.
- **Jev (optional).** With `decider = "jev"`, the text of a request (and the monster's last sentence, for follow-ups) is sent to TypeSafe's API for yes/no and choice decisions. Nothing else, and never audio.
- **Honest limit.** UI control means the agent acts with your permissions in apps that are not blocked. Watch it work, and say "Hey Monster, stop" or press Ctrl+C to cancel.
- **Local confirmation.** Sleep, shutdown, restart, and plans that type into the focused window need your spoken "yes" or a click on Approve. A model cannot supply or skip it.
- **Sandboxed output.** Files are written only to `Documents\LazyMonster` and are never overwritten.
- **Generated text is data.** Text written by a model can fill a document but is never executed or turned into new steps.
- **What leaves your PC.** Wake word, speech recognition and instant commands stay local. Open-ended requests are sent to the configured provider: text for the planner, audio for the realtime voice session.
- **Keys** are read from environment variables and never logged or shown in the UI.

## Known risks

- Anyone within earshot, or a video playing nearby, can say "Hey Monster". Risky actions need confirmation for this reason. Keep `require_prefix = true`.
- Content you ask it to write comes from a language model and can be wrong.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting ("Report a vulnerability" on the Security tab). We aim to respond within 7 days.
