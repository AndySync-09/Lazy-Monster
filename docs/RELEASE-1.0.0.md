# Lazy-Monster 1.0: say it, the monster does it

A voice agent for your Windows PC. Say "Hey Monster" and it opens apps, writes the document, builds the slides, researches the web, runs the code it writes, and closes everything when you're done.

## Install (one command, no admin rights)

Open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex
```

## What's in 1.0

- **Hears you, not the room.** A personal "Hey Monster" wake word on the Intel NPU, a voice lock that only answers your voice, and push-to-talk on Ctrl+Alt+Space.
- **A real conversation.** It waits for you to finish, remembers the thread, answers "yes" and "the second one", and you can interrupt it.
- **Your choice of brain.** OpenAI or Claude, picked at install, with optional Jev by TypeSafe for split-second decisions: it ignores room chatter, routes each task and understands a casual "yes".
- **Real work in real apps.** Word, PowerPoint, VS Code, your browser and files, with every step checked. Web research with sources.
- **Safe by design.** No terminals, no deleting, no sending, no buying. Risky steps wait for your "yes". "Close everything" only touches what it opened, and asks about unsaved work.
- **Every chip gets a job.** Wake word on the NPU, speech on the Arc GPU, voice on the CPU.
- **Remembers your work.** "Welcome back, Andy. Want to pick up the cafe site?"

## Requirements

Windows 10 or 11, a microphone, about 3 GB of space. An OpenAI API key for bigger tasks (instant commands work without one). An Intel AI PC is optional.

## Coming next

macOS, next week. Watch this repo (Watch → Custom → Releases) to hear first.
