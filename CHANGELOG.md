# Changelog

## 1.7.4
- **Fix: it stopped hearing you (1.7.3).** The own-voice filter judged every half-finished line: after "Hi Andy, what can I do for you?", the first words of your reply ("hey monster can you…") matched its own words and the whole request was thrown away. Now only a finished line can be dropped, and only when it's at least three meaningful words, nearly all of them just said by the monster; everyday words ("can", "you", "what", "yes") never count.

## 1.7.3: it doesn't hear itself
- **Its own voice no longer lands in a running task.** On a TV over HDMI, a soundbar or Bluetooth, sound arrives late and loud, so the end of the monster's sentence reached the mic after it stopped talking and was taken as something you said. Now the mic stays shut longer after it speaks on those outputs (0.9 s, 0.35 s on laptop speakers, 0.15 s on headphones; `echo_tail` to set your own), anything heard that is mostly words it just said is dropped, and during a task a scrap of audio too short for the voice lock to judge no longer counts as you.
- **Interrupting by talking on loud speakers** needs the voice lock to recognise you; without a voice lock, only "Hey Monster" interrupts there.
- The log records the output device it detected and each echo it ignored.

## 1.7.2: stars and news
- **Live star counter** in the site's header, counting up from GitHub (cached for an hour per visitor).
- **What's new strip** under the hero, showing the latest releases from this changelog; it rotates through the last four and refreshes from the repo when it can.
- **The header fits at every width:** links and buttons step back as the window narrows.

## 1.7.1: lazymonster.space
- **The site moves to lazymonster.space** (`docs/CNAME`), served by GitHub Pages.
- **A punk layer:** film grain, a glitching headline and a tilted ticker.
- **Meet the monster:** moods, skins, outfits, Brain-Break, and a button that dissolves it into the particle monster and back.
- **The 40-second film** on the site, landscape or vertical.
- **Site source in `site/index.html`:** `python tools/build_site.py` builds `docs/index.html` as a small JavaScript loader around the compressed page; title and social-preview tags stay plain HTML.

## 1.7.0: Brain-Break
- **Brain-Break: it keeps working offline.** A light connection check every 20 seconds (nothing is sent). After two misses the monster puts on its headband, the status bar turns yellow and says "Brain-Break · on-PC brain", and it tells you. Simple requests go to the quick brain on your PC (even if the quick brain is normally off, it's borrowed for the break). If your main brain is local (Ollama, llama.cpp, vLLM on this PC or your network) everything keeps working. Anything that needs the internet is kept, and when the connection is back it offers the last one again.
- **Minimise button on the sleeping orb.** Hover the orb for a small button that sends it to the tray; "Hey Monster" or Ctrl+Alt+Space brings it back.
- **New README.** A developer write-up: the NPU/GPU/CPU split with measured numbers, Brain-Break, every model that ships with its license, why an AI PC makes this better, an animated architecture diagram, and animated icons.

## 1.6.3
- **Fix: "close everything" closed the monster too.** "Close everything", "close all windows" and "close it all" now always mean the careful close: only what the monster opened, asking about unsaved work. On top of that the monster can't close itself any more: its own window is never recorded as something it opened, "close" can't target it (by name or process), close keys aren't pressed while its window is in front, and closing its window (Alt+F4 or any other way) just hides it. Only Quit in the tray ends it.
- The quick brain hands "close everything" to the main brain instead of guessing an app called "everything".
- Labels name the device the quick brain actually runs on (it was chosen on the GPU).

## 1.6.2
- **Quick brain on the GPU: 0.6 s.** Measured on a Core Ultra 9 185H: the same Qwen2.5 1.5B model took 3.8 s per request on the NPU and 0.6 s on the Arc GPU, so the benchmark now prefers whichever is faster at equal accuracy.
- **Accuracy back up.** The short prompt from 1.6.1 cost accuracy (11/12 fell to 7/12); on the GPU prompt length barely matters, so the descriptive prompt is back with more examples. Where OpenVINO supports it, the output is constrained to real tool names, so the model can't invent "play_music". Near-misses ("mute()", "play_music", "open github.com" as an app) are mapped to the real tool.
- **Honest scoring.** The benchmark applies the same "clearly big" filter the monster uses, and counts a hand-off to the main brain as safe (just slower), separately from a wrong action. It picks a model only if it's right at least 70% of the time with at most one wrong action.

## 1.6.1
- **Quick brain, faster.** On the NPU most of the 3.5 s went into reading a long prompt, so the prompt is now about a third of the size, and the model no longer writes the spoken confirmation (the monster fills it in: "Opening Spotify."), so it writes a third as much.
- **No wait for big requests.** Requests that are obviously bigger (research, code, slides, email, files, the screen, "and then…", or more than 14 words) skip the quick brain and go straight to the main brain.
- "Play some music" now plays music instead of opening an app.
- `monster bench-brain --device all` runs the chosen model on the NPU and the GPU and keeps the faster one that's as accurate.

## 1.6.0: a brain on the NPU
- **Quick brain (preview).** A small language model on the Intel NPU handles simple one-step requests ("open Spotify", "volume 40", "remind me in 20 minutes to stretch", "write a haiku in Notepad", "why is my laptop slow") without the cloud: it answers with one line of JSON naming the tool, the monster checks it against the same rules as always, and does it. Anything with several steps, research, code, documents, email or the screen, or anything it isn't sure about, goes to the main brain as before, and so does anything whose action fails. The status bar shows "+ NPU" when it's on.
- **`monster bench-brain`** downloads the candidates (Qwen2.5 1.5B builds for OpenVINO, and the Qwen2.5-VL 3B NPU build already used by bench-vision), times 12 everyday requests on the NPU, counts how often each picks the right tool, and keeps the best one that's right at least 75% of the time. Then `monster brain --quick on`, or Settings > Brain > Quick brain on the NPU.

## 1.5.1
- **Watchdog.** The sign-in entry now starts a small supervisor that runs the monster; if the monster dies without you quitting it, the supervisor saves a crash report (exit code, how long it ran, the last 120 log lines, any native crash trace) and starts it again within seconds, up to 5 times in 10 minutes. The monster tells you it restarted and where the report is. `monster crashes` shows the latest one. Quitting from the tray or `monster service stop` is never treated as a crash.
- `monster bench-vision`: the model download retries and resumes instead of stopping with a traceback when the connection is reset, and `--mirror` downloads through hf-mirror.com.
- `.gitattributes` keeps line endings as LF, which silences Git's "LF will be replaced by CRLF" warnings on Windows.

## 1.5.0: alive
- **Mascot → monster.** When a task starts, the mascot breaks apart into particles that become the particle monster: the decision tree, the typing page, falling branches. When it's done, the particles fly back together into the mascot, which hops.
- **Eyes that follow your pointer** (anywhere on screen, on Windows) while it listens or talks, and **idle moments** while it naps: a yawn, a stretch, a one-eyed peek at you. A coffee cup in the morning, a sleep mask late at night.
- **Skins:** Classic violet, Mint, Sunset, Midnight, Bubblegum. **Outfits:** seasonal by default (Diwali lights from 20 Oct to 15 Nov, a winter hat over Christmas, a cricket cap in IPL season), or a party hat, sunglasses, or none. Settings > Look.
- **Desktop pet mode** (Settings > Look, experimental): while it naps as the small orb, it walks along the top of the taskbar, turns at the edges and stops for naps. On Windows the orb's background is made see-through with a colour key; if your system draws it as a dark box instead, tell us.
- **Reading the screen on this PC.** When a window's text can't be read directly (a remote desktop, an image, a PDF shown as a picture, a game), "what's on my screen" reads the text from the screenshot with PP-OCRv4, compiled through OpenVINO at fixed shapes so it can run on the NPU (falling back to the GPU, then the CPU). The same text as ONNX Runtime, measured.
- **Screenshots stay home by default.** Cloud brains now get the window's text and the text read on your PC, not the image, unless you turn on Settings > Privacy > "Let cloud brains see screenshots". A local brain (Ollama, llama.cpp) always gets the image, since it never leaves the PC.
- **`monster bench-vision`**: times on-device OCR on NPU/GPU/CPU and a small vision model (Qwen2.5-VL 3B, INT4, an NPU-targeted OpenVINO export) on each, with its answer, so we can decide where full on-device vision should run.
- The status bar keeps its labels in compact mode.

## 1.4.0: the monster sees
- **It no longer falls asleep mid-task.** "On it" finished, the monster checked a handful of flags, found none set at that instant, and went to sleep while the brain was still working. A running task is now an explicit state that nothing else overrides; slow tasks show "still working… 12 s".
- **The animated mascot.** The character from the logo, drawn in SVG and animated with CSS (no particles): it breathes and floats Zs when asleep, opens its eyes and tilts its head while listening (with a glow that follows your voice), looks up with thinking dots while it decides (with the options it's weighing shown as pills), sticks its tongue out with a page while working, talks while speaking, hops when done and frowns on an error. It's the default look; "Particles" is still in settings. The README and website use a sleeping version that peeks now and then.
- **It knows how your PC is doing.** "Why is my laptop slow?", "check my CPU usage", "what's using my memory?": CPU, memory, GPU load and shared GPU memory, disk, battery and the busiest processes, read directly (no Task Manager), with plain hints ("most of the memory is held by the GPU, often a local AI model server"). Works without a brain too, with a short spoken summary.
- **It can see your screen, when you ask.** "What's on my screen?", "explain this error", "summarise this page": it reads the front window's text and takes a screenshot of just that window for a brain that can see (GPT, Claude, or a local vision model such as Qwen 3.5 or Gemma 4; others get the text only). The screenshot stays in memory for that one question and is never saved; private windows (passwords, keys, banking) are refused.
- Checking a new model gives up after 30 seconds with a reason ("the model may still be loading, or the machine is short on memory") instead of waiting 3 minutes.

## 1.3.3
- Local thinking models (Qwen3, Qwen3.5, DeepSeek-R1 in Ollama) no longer have their `<think>` reasoning spoken aloud or shown.

## 1.3.2
- Fix: the window could go full screen (double-clicking its title strip maximised it). It can no longer be maximised, and if anything does, it snaps back to its corner size within a second or two. Tray: "Back to the corner".

## 1.3.1
- **Fix: your voice was swapped for the Windows voice.** 1.3.0 used numpy in the Kokoro voice without importing it, so every sentence failed and quietly fell back to Windows' own voice; changing the voice in settings did nothing because Kokoro wasn't speaking at all. Fixed, and a fallback now shows a note in the window (and the Windows fallback prefers a female voice).
- Changing the voice in settings says a sentence in the new voice right away; a preview no longer leaves the preview voice behind.

## 1.3.0: reminders that come to you
- **Reminders.** "Hey Monster, remind me about the cafe website meeting at 8 AM" (also "in 20 minutes", "tomorrow morning", "tonight at 7"). At that time the monster wakes up by itself, pops up, sends a tray notification, says it, and suggests up to three things it could do next from your recent work (open the project, update the code, draft an email). It waits for your pick ("the last one") and does nothing until you choose; if you're away (brushing your teeth), it checks once more five minutes later. "What are my reminders", "cancel the cafe reminder", "snooze for 10 minutes". A reminder missed while the PC was off still fires up to 3 hours late.
- **Email drafts.** `draft_email` opens a filled-in draft in your mail app. You review and send; the monster never sends.
- **Your own voice, recognised better.** The voice lock now listens only to the speech (not the silence around it), compares against each of your enrollment takes, and lowers the bar for short commands (measured: "mute" in the enrolled voice scored 0.62-0.70 against a 0.72 bar, so it was wrongly refused). Push-to-talk requests teach it how you sound on your mic and in your room (last 20 kept). Enrolment thresholds are now 0.45-0.68.
- **Interrupting fixed.** It no longer depends on the voice lock passing on mixed audio. While the monster talks, the mic hears its voice at a steady ratio; when you talk over it the mic gets much louder than its echo explains, and it stops. The voice lock only vetoes voices that are clearly someone else (a TV).
- **Changing models fixed.** A new model or brain is tried first (it must answer and use tools); if it can't, the monster keeps the one that works and says why ("gpt-5.4-pro didn't work … I kept gpt-5.4-mini"). The model list hides models that can't drive apps (audio, realtime, embeddings, instruct, codex).

## 1.2.1
- Fix: the settings panel shrank into the sleeping orb after a few seconds. While settings are open (or you're typing in the box) the window stays full size; it goes back to the orb a few seconds after you close them.
- **Save & close** at the bottom of settings: saves anything still typed in (a key, the local address, the push-to-talk key, a picked brain) and confirms.
- **The monster icon everywhere**: on the window itself (Alt+Tab, title, any taskbar button) instead of Python's, and a crisper tray icon. The tray-only window style is now re-applied after every show and orb change, and logs if Windows refuses it.

## 1.2.0: settings, live brains, real conversation
**Change anything, live**
- **Settings panel** (gear icon, or tray > Settings…): brain (OpenAI, Claude, Local), the model (listed live from your key or server, so new models show up by themselves), a Test button, paste a key, the local address, go big, Jev, the voice with a preview, conversation mode, interrupt-by-talking, voice lock, wake sensitivity, push-to-talk key, retrain voice, left or right corner. Changes apply without a restart (push-to-talk key and Jev after one).
- **By voice:** "switch to Claude", "use OpenAI", "use the bigger brain", "go back to the normal brain", "which brain are you using?"
- **`monster brain`**: `--list` models, `--provider claude`, `--use <model>`, `--big on|off`, `--test`. `monster models --refresh` re-downloads the newest speech and voice models. The app checks GitHub once a day and says when an update is out (`monster update`).

**Lives in the tray**
- On Windows the window no longer has a taskbar button or a Python icon: it's a tool window with its own identity, and the tray icon is its home ("Show Lazy-Monster" on click). The Start menu entry brings up the running monster instead of starting a second one.

**Conversation**
- **Conversation mode** (on by default): after every reply it keeps listening for about 20 seconds without "Hey Monster"; "that's all" ends it. The voice lock (and Jev, if on) keep room chatter out.
- **Interrupt by talking**: talk over the monster and it stops, if your voice passes the voice lock. Its own voice and the TV can't do it.
- **Smarter end of turn**: after "open the…" it waits twice as long; after a finished question or a command it already understands, it answers sooner. What you said over the monster is kept for your next turn.

## 1.1.0: your brain, your corner
- **No brain, no go.** The installer finds the keys you already have and says "Monster Brain: OpenAI. Keep it, switch brain, or make the monster go big?" With no key it asks until one works (or you quit). "Go big" (hard tasks on GPT-6 Astra or Claude Sonnet 5) is now opt-in: `go_big = true`.
- **Local brains.** Ollama, llama.cpp, vLLM, LM Studio or any OpenAI-style endpoint (`planner = "local"`). The installer finds servers on the usual ports, lists their models, and tests that the model can call tools before accepting it, with the exact flag to fix it if not. A local brain can still go big on a cloud model if you add a key.
- **Web research with any brain.** Local brains search DuckDuckGo (no key) or Brave Search (`BRAVE_API_KEY`), read the top pages and summarise them with numbered sources.
- **Retrain your voice from scratch.** The installer offers "keep it or start fresh"; `monster voice-reset --train` and the tray's "Retrain my voice…" do the same any time. Wake-word training now also records 20 seconds of your room (typing, fan), which is what false wakes are made of.
- **A new top of the window.** An animated status bar replaces the text chips: ears (pulse when listening), the brain (provider colour, a spark when it goes big), the voice lock, and live chip meters; a glowing line under the title shows the mood (violet asleep, lime listening, pink speaking). Details on hover.
- **Bottom-left, and it stays where you put it.** Starts in the bottom-left corner, remembers where you drag it, the sleeping orb sits on the same side, and "Hey Monster, move to the right" works.
- Fixes: the welcome-back recap only lists real work, in the monster's own words ("Last time, I built a snake game in VS Code"), never "Yes, please do that…" or "to thirty percent". Without a brain it says once that it needs one, instead of a column of "didn't catch that".

## 1.0.4
- **No more greetings out of nowhere.** The wake word now gets a second opinion before the monster wakes: Whisper re-hears the last two seconds (without its vocabulary hint, so it can't imagine the word) and must hear "monster", and with the voice lock on it must sound like you. A false wake stays completely silent (logged as `wake ignored`).
- The detector itself is stricter: your trained threshold instead of a cap at 0.85, and three hits in a row instead of two. Tune with `wake_sensitivity`.
- "Hi Andy, how can I help?" at most every 30 minutes; other wakes just chime.
- `service status` / `doctor` counted one monster three times (on Windows each is a chain of launcher processes). Now it counts monsters, not processes.

## 1.0.3
- **Fix: the background monster quit right after starting** (`running: 0`, so neither "Hey Monster" nor Ctrl+Alt+Space answered). The voice lock's speaker model (sherpa-onnx) ships its own onnxruntime DLL, and loading it into the same process as the Kokoro voice's onnxruntime crashes on Windows without a Python error. The voice lock now runs in its own small helper process and answers over a pipe; if the helper is slow or gone, it lets you through rather than locking you out.
- Native crashes now leave a trace in the log (faulthandler), and startup logs each step (microphone, voice lock, push-to-talk, wake word), so `monster service status` shows where it stopped.
- `monster doctor` checks that exactly one background monster is running.

## 1.0.2: Jev, done right
- **Jev is a decider, not a brain.** 1.0.1 treated Jev as a chat model. It isn't: TypeSafe's Jev answers typed questions (yes/no probability, a choice, a score) through its System One API (`POST https://api.typesafe.ai/v1/systemone`). The brain stays OpenAI or Claude; with `decider = "jev"` Jev makes the quick calls around it:
  - **"Was that meant for me?"** In the follow-up window (no wake word), speech that isn't addressed to the monster is ignored: phone calls, TV, talking to someone else.
  - **Which tool, how hard.** One call at the start of each task gives the decision tree Jev's real probabilities, and hard tasks start on the stronger model straight away.
  - **Did you say yes?** "Sure, go for it" counts as yes for running code or installing packages.
  - Short timeout and no dependency: if Jev is down, everything works as before.
- The installer asks for the brain (OpenAI or Claude), then offers Jev with its TypeSafe key and a live test question. `monster doctor` checks Jev too.

## 1.0.1
- **Choose the brain first.** The installer starts by asking OpenAI, Claude (Anthropic) or Jev (any OpenAI-compatible endpoint), checks the key, and only then installs. `planner = "anthropic"` uses Claude through the Messages API (web research through Claude's web search tool); updates keep your choice.
- **The monster-themed setup.** Mascot, colours and a live mic meter. Wake-word training and voice enrollment listen for you by themselves: no Enter before every take, a take stops when you pause, and silent or partial takes are redone.
- **Voice lock can't lock you out.** Takes that don't match the rest are re-recorded; if your takes still don't agree (noisy room), the lock stays off instead of saving a bad voiceprint (1.0.0 saved one with 0.44 consistency, which ignored you). When it does ignore a voice after "Hey Monster", it says so once and tells you to press Ctrl+Alt+Space. `monster voice-lock on|off`.
- **Make it yours:** `monster voices` (list, hear, pick), your own Kokoro-format voice files, your own Whisper export as a folder. See docs/VOICES.md.
- `monster service status` shows the brain, voice lock and push-to-talk state, and the key startup lines from the log.

## 1.0.0: first release (Windows)
Lazy-Monster's first public release, for Windows 10 and 11. Everything in 0.1 to 0.11 below, installable with one command:
`irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex`

## 0.11.0: macOS groundwork (unannounced preview)
- **One command on a Mac:** `curl -fsSL https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.sh | bash`. Installs to `~/.lazymonster` (no sudo), Python via Homebrew if needed, the OpenAI key into your Keychain, voice models, walks through the macOS privacy switches (`monster permissions`), learns your voice, and starts at login (LaunchAgent). Re-run to update; `uninstall.sh` removes it.
- **Hearing on macOS:** streaming speech via sherpa-onnx (Zipformer, CPU, ~8% of a core; Moonshine's streaming build isn't published for macOS). Whisper re-hears each request with MLX on the Apple Silicon GPU (distil-large-v3) or faster-whisper on Intel Macs (small.en). The wake word and voice lock run on ONNX Runtime.
- **Doing on macOS:** apps and files via `open`, windows and buttons via AppleScript and the Accessibility API, text pasted through the clipboard and read back to verify, Word-style documents saved as .docx, PDF export through Word for Mac, decks as .pptx. "Close everything" quits apps it launched itself (each app asks about unsaved work) and stops programs it ran.
- Push-to-talk on macOS: Cmd+Shift+Space. No menu-bar icon yet (the window needs the main thread); quit with `monster service stop`.
- Wake-word features fall back to ONNX Runtime anywhere OpenVINO is missing (checked equal to OpenVINO: embedding cosine 0.99997).

## 0.10.1: one-command install and a website
- **One command:** `irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex` in PowerShell. It finds or installs Python (winget, per user), installs to `%LOCALAPPDATA%\LazyMonster\app` in a private environment, asks for the OpenAI key (optional), downloads the voice models, offers to learn your voice, starts the background service, adds a Start menu entry and puts `monster` on your PATH. No admin rights. Re-running it updates and keeps settings, voiceprint and models.
- `monster update` re-runs the installer; `uninstall.ps1` removes the program and asks before deleting your voice and settings.
- The website lives in `docs/` for GitHub Pages: animated night sky, interactive particle monster demo, voice demo, companion monster, install, FAQ and comparison.

## 0.10.0: knows your voice
- **Sleep to orb.** "Hey Monster, sleep" (in any window mode) shrinks it to a small sleeping monster at the screen corner, still listening. "Hey Monster", the push-to-talk hotkey, or a click on the orb brings the full window back. Quit only from the tray.
- **Voice lock.** `monster voice-enroll` (five sentences, about a minute) saves a local voiceprint (TitaNet-small speaker model via sherpa-onnx, on the CPU, ~50 ms per request). From then on it acts only on your voice: a TV, a video or someone else saying "Hey Monster, delete..." is ignored. Typed requests and push-to-talk always work. `monster voice-test` checks it; tray toggle "Voice lock".
- **Push-to-talk.** Ctrl+Alt+Space (`push_to_talk`) starts listening from anywhere, no wake word, and interrupts it if it's talking. Also "Talk now" in the tray and a click on the monster.
- Fix: `setup.ps1` stops the background copy before reinstalling (a locked `monsterw.exe` left 0.9 installs without `monster.exe`).

## 0.9.0: hears you, not itself
**Hearing**
- The monster's own voice (and its echo) is cut out of the audio Whisper re-hears, so its greeting or questions can no longer end up in your request.
- After a task it only keeps listening without "Hey Monster" when it actually asked you something (10 s). Otherwise room chatter and music are ignored until the wake word.
- No reflexive "What next?" at the end of every answer.

**Doing**
- `open_file`: opens the pages, PDFs, decks and documents it made, in their default app or in Chrome/Edge/Word/PowerPoint. Documents and media only, from your own folders.
- `export_pdf`: the current Word document as a PDF, opened.
- `make_presentation`: a real .pptx built from an outline (title slide, clean layout), opened in PowerPoint.
- `web_research`: an actual web search with sources (OpenAI web search), instead of answering from memory.

**Thinking**
- Acts first with sensible defaults and says what it chose; at most two questions per task; a step budget of 8 before it wraps up.
- Approve running or installing once per project per session.
- Hard or failing tasks (2 failures, or more than 6 steps) move to a stronger model (`escalation_model`, default `gpt-6-astra`); if that model is unavailable it carries on with the normal one.

**Reliability**
- Exactly one background copy: the single-instance check read the Windows error the wrong way (0.8 could run three), and `service install` now replaces running copies.
- Many ways to say "go to sleep" ("you can sleep", "go sleep", "that's all", "stop listening"), plus a sleep tool the agent can use.
- Finish text that arrived as raw JSON is spoken as a sentence.
- Log readable in PowerShell; each task logs its time to first action; the window shows steps and seconds per task.

## 0.8.0: tidy and remembers
- **"Hey Monster, close everything"** (or "clean up", "I'm done") closes what the monster opened this session: app windows, the Notepad tabs it wrote in (only those, never your other tabs), Word documents, VS Code windows and programs it ran. Things it did not open are never touched.
- **Unsaved work: it asks.** "Notepad has unsaved changes. Should I save it? Tell me a name or a place, or say no." Say a name ("save it as Bangalore poem"), a place ("on the desktop"), both, or "no". If you just say yes or don't answer, it saves to your default folder, `C:\temp` (`default_save_dir`), with a suggested name, and tells you exactly where.
- **Remembers your work.** Every finished task goes into a local journal (`%APPDATA%\lazymonster\journal.jsonl`, with files it saved). On the first "Hey Monster" after starting, it says: "Welcome back, Andy. Recently we worked on: a snake game in VS Code, and a haiku about Bangalore traffic. Want to pick one of those up, or start fresh?" Answer naturally; "the snake game" resumes it. Ask "what did we work on?" any time.
- Spoken file paths are readable: "haiku.txt in temp" instead of a raw path.

## 0.7.0: always there
- **Background mode.** `monster service install` starts Lazy-Monster at sign-in with no console window (`monsterw.exe`), hidden until you say "Hey Monster". The window appears on wake and hides again after 45 s asleep (`hide_after`). One copy per user. Output goes to `%APPDATA%\lazymonster\monster.log`. Also `service uninstall | start | stop | status`.
  A true Windows service runs in session 0 with no microphone or desktop, so this uses the per-user sign-in entry instead (no admin rights).
- **Greets you by name.** After a bare "Hey Monster" it says "Hi Andy, how can I help?" (first name from your Windows account; override with `user_name`). If you keep talking straight after the wake word, it skips the greeting and just listens.
- In the background, "Hey Monster, sleep" and the window's close button hide it and keep listening; quitting is in the tray ("Quit Lazy-Monster") or `monster service stop`.

## 0.6.0: a real conversation
- **One conversation state machine** (`conversation.py`): sleeping, listening, thinking, acting, speaking, awaiting your reply. The window, sounds, microphone gating and wake-word handling all follow it, replacing seven separate flags that drifted out of sync.
- **Turn-taking.** Pauses no longer cut your request in half: lines are joined into one turn until you have been quiet for 0.9 s (`turn_delay`). Instant commands still fire at once, even across a pause ("open ... notepad"). Whisper re-hears the whole turn.
- **Conversation memory.** One-word replies ("snake", "yes", "the second one") go to the agent while you are mid-conversation instead of being dropped.
- **Wake word by state.** Sleeping: wakes. Speaking: barge-in, ignoring the first moment of its own voice and requiring a confident score. Listening, thinking or working: ignored, with no beep and no re-arm.
- **Three sounds only:** a soft wake chime, a done chime, an error tone (generated in memory). No other beeps.
- **Talks like a person:** a short "On it" when a task starts, one progress line if a task runs past 10 s, short answers with one useful offer, no em dashes or lists.
- **Chat view:** your turns and the monster's replies as bubbles under the monster, with each task's steps folded into its reply; a speaking animation.
- Fixes: "Code" in a VS Code title no longer counts as a sensitive window; project environments live in `%LOCALAPPDATA%\lazymonster\venvs` (outside OneDrive, which locked files during creation) and are created from the base Python, with the real error shown if creation fails.

## 0.5.5
- Fix: the wake word loaded on the NPU but never fired. The mel front end computes log(max(x, 1e-10)); in the NPU's FP16, 1e-10 underflows to zero and log(0) is -inf, so every feature was garbage. The front end (tiny) now runs on the CPU; the embedding network runs on the NPU only if it reproduces the CPU output (cosine >= 0.99), otherwise it falls back and says why.
- Detection threshold capped at 0.85 (two consecutive hits still required).
- `monster wake-test`: live score meter, peak score, and a suggested `wake_sensitivity` if it misses you.

## 0.5.4
- Whisper: generation is capped at 96 tokens (commands are short), and warm-up uses quiet noise instead of digital silence, which made Whisper hallucinate long output and overflow the NPU's fixed decoder cache. The vocabulary prompt now resets per device, so the GPU fallback keeps it (0.5.3 dropped it after the NPU attempt).

## 0.5.3
- Whisper on the NPU: the NPU pipeline has a fixed-size decoder window and the 60-word vocabulary prompt overflowed it (`roi_end <= max_dim`). Warm-up now shrinks the prompt to 12 words, then drops it, before falling back to the GPU. `monster models` reports which it used.

## 0.5.2
- Wake word on the NPU: the NPU compiler rejected a `Maximum` op in the mel front end (`failed to legalize IE.Maximum`), so everything fell back to the GPU. The graph is now rewritten to NPU-friendly ops (Clamp / Relu arithmetic, bit-identical on CPU), and each feature model picks its own device, so the embedding network stays on the NPU even if the front end cannot.
- When Whisper falls back from the NPU, the reason is printed.

## 0.5.1
- **The monster can run the code it writes.** New `code_run` and `code_install` tools. Each project gets its own virtual environment inside `Documents\LazyMonster\code\<project>\.venv`; packages never touch Lazy-Monster's or the system's Python.
- Safety: before running or installing, the monster asks you out loud and waits for your "yes" (decided locally, not by the model). It only runs `.py` files it wrote itself and that are unchanged since (tracked by hash in `.lazymonster.json`), with a fixed interpreter and no arguments. Package names must be plain PyPI names (no URLs, paths or pip flags). Terminals stay blocked.
- Crashes come back to the agent with the error; a missing package is suggested for `code_install`.

## 0.5.0: the monster feels alive
- **Personal "Hey Monster" wake word on the NPU.** `monster wake-train` records ~15 of your "Hey Monster"s plus a little normal talk and room noise, adds synthetic Kokoro voices (US, UK and Indian English, several speeds) and look-alike phrases ("hey mister", "a monster movie"), and trains a small detector on top of openWakeWord's speech features. The features run through OpenVINO at fixed shapes on the Intel NPU. In a synthetic test with voices it never trained on: recall 100%, no false wakes on look-alike phrases at the chosen threshold. Your real-world numbers print after training.
- **CPU transcriber sleeps while idle.** With the NPU wake word, Moonshine only listens after "Hey Monster" (and during follow-ups and tasks). Whisper still re-hears the full request, including the first word.
- **Barge-in.** Say "Hey Monster" while it is talking, click the monster, or use the tray, and it stops mid-sentence and listens.
- **Tray icon.** Show/hide, pause listening, stop talking, pick the voice (Heart, Bella, Nicole, Emma, and two Indian English voices), open the output folder, settings and history, sleep. Voice choice persists in `settings.toml`.

## 0.4.1
- Fix: the window hung at start. pywebview publishes every public attribute of the page API to JavaScript and walked the native window object recursively. The API now exposes only `submit`, `sleep` and `compact` (also closes a path from the page to engine internals).
- Model downloads retry with backoff and end with a clear message (with a mirror hint) instead of a traceback; `monster models` says when it is compiling for the NPU.

## 0.4.0: the monster gets a face and a local voice
- **UI** (`monster` or `monster ui`): an always-on-top window with a particle monster driven by real events. It sleeps, listens (waveform follows your mic), grows a decision tree from the agent's reported candidate actions (blocked branches turn red and wither, the chosen one turns lime), writes, asks, and confirms. Transcript, verified steps, Approve/Cancel, one-tap "yes" to the suggested next step, and a text box.
- **Local speech, two passes:** Moonshine streaming for the wake phrase and instant commands; every agent request is then re-heard by distil-Whisper large-v3 (INT8) through OpenVINO GenAI on the **NPU** (GPU/CPU fallback), with a vocabulary prompt (Bangalore-area names, your apps, your `vocabulary`).
- **Local voice:** Kokoro-82M (Apache 2.0), female voice `af_heart` by default, sentence-streamed so it starts talking in under a second. Runs on the CPU. OpenAI and Windows voices remain as options.
- **Exact text:** text is pasted line by line through the clipboard (your clipboard is restored) instead of simulated keystrokes, which garbled text in Windows 11 Notepad.
- **Self-check:** every write reads the document back and reports verified or MISMATCH; Word checks the document text; code files are re-read and Python is syntax-checked. New `read_text` tool.
- **Window targeting by handle:** the monster types into the window it opened or focused, never a look-alike.
- **Speed:** `write_in_app` does open + new document + paste + verify in one step; `reasoning_effort = "low"` by default (dropped automatically if unsupported).
- **Cross-platform groundwork:** macOS/Linux executor (open apps and URLs, type/keys via System Events or xdotool on X11, volume, media, lock, files, VS Code). Window reading, clicking and Office stay Windows-only for now. CI runs on Windows, macOS and Ubuntu.
- `monster models` downloads and prepares the local models and reports where they run.

## 0.3.1
- Fix: after "Hey Monster" + pause, a long command was dropped if it finished after the listening window. The window now applies to when you start speaking.
- Wake phrase also accepts "You monster", "Me monster", "Here, monster" at the start of a line (common mishearings).

## 0.3.0: the monster talks back
- Spoken replies (OpenAI `gpt-4o-mini-tts`, falling back to the Windows voice; `--quiet` or `voice = "off"` to silence). The mic is muted while it speaks.
- After every task it says what it did and offers the most useful next step ("Want me to save it?"). Say "yes" to do it, "no" to move on, or give a new task.
- When stuck or blocked it asks you a specific question instead of giving up; two failures in a row force a question.
- "Write ..." now goes to the agent (it writes content); "type ..." still types your words verbatim.
- Safety after a field incident (typing into a restored Notepad tab holding recovery codes):
  - Sensitive windows (passwords, recovery codes, keys, tokens, .env, wallets, banking) are never typed into, clicked in or read, and their titles are redacted before reaching the model.
  - Ownership: the monster only edits new/untitled documents or documents you named; otherwise it opens a new one (Ctrl+N) or asks.
- `monster say` tests the voice.

## 0.2.4
- "Hey Monster, sleep" (also exit, quit, goodnight, bye) closes Lazy-Monster. Putting the PC to sleep now needs "put the computer to sleep".
- Speech heard while a task is running goes to that task, no wake phrase needed ("save it" while a save dialog is up).
- New `ask_user` tool: the agent asks instead of guessing on choices that lose work, and waits for your answer.
- `click` reports the button it pressed even when the dialog closes.

## 0.2.3
- Fix: `click` crashed (slot named `name` clashed with `Intent.make`), which broke clicking dialog buttons such as Save.
- Fix: `close_app` now resolves app names the same way as `open_app` ("Notepad" works).
- A malformed tool call now returns an error to the agent instead of ending the task.

## 0.2.2
- Follow-ups: after a task, the monster listens 15 s without the wake phrase, and the agent remembers the session for 3 minutes ("Hey Monster, open Notepad and type hello" ... "save it").
- `open_app` reports the focused window, saving the agent two or three round trips per task.
- Silenced the remaining pywinauto COM warning.

## 0.2.1
- Wake phrase: accept "A monster" / "Hay monster" (common transcriptions of "Hey"), and the bare name at the start of a line.
- "Cancel it", "stop it", "stop now" cancel a running task.
- Wake window after a lone "Hey Monster" extended to 8 s; one-word leftovers are not sent to the agent.
- Silenced the pywinauto COM threading warning.

## 0.2.0: the monster gets hands
- Agent loop with tool calling: sees tool results and window contents, works until done, and can be cancelled by voice ("Hey Monster, stop") or Ctrl+C.
- New tools: list/focus/read windows, click, press keys (allowlisted), VS Code projects with live-streamed files, visible Word typing.
- Local guards for input targets, risky clicks, banned shortcuts and code paths.
- NPU ready: OpenVINO bundled, `monster npu` detects and benchmarks NPU/GPU/CPU, `accelerator` setting.
- `monster do <task>` runs one task and shows each step.

## 0.1.0: first preview
- "Hey Monster" wake phrase, spotted in the on-device streaming transcript.
- Instant lane: 25 typed commands with semantic endpointing (fires on a stable partial, not a silence timeout).
- Agent lane: OpenAI planner with a forced `submit_plan`, local validation, `$N` step references, and Word automation via COM.
- Safety: typed allowlist, local confirmation, `Documents\LazyMonster` sandbox, no overwrite.
- CLI: `run`, `text`, `plan`, `doctor`, `apps`, `bench-text`, `record`, `bench-audio`.
- Setup enforces a project virtual environment.
