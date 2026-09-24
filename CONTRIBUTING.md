# Contributing to Lazy-Monster

Thanks for helping the monster do less while you do even less.

1. Fork, then set up the project:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
2. Make your change on a branch.
3. Run the tests:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
4. Open a pull request using the template.

## Rules

- **New abilities are typed tools.** Add them to `lazymonster/intents.py`, implement them in `lazymonster/actions/`, and add tests: valid args, bad types, out-of-range values, and use inside a plan.
- **Safety invariants are not negotiable.** Read the list in `CLAUDE.md` and `SECURITY.md`. PRs that add a shell, delete, send or purchase capability will be closed.
- **No emojis** in code, UI, docs or commit messages. Use or extend the SVG icons in `docs/assets/icons/`.
- Keep the instant lane fast: no network or model calls in `grammar.py` or `engine.on_partial`.
- Commit messages: imperative mood, for example "Add Excel write_cells tool".
