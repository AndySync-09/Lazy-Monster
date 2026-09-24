class DryRunExecutor:
    """Records steps instead of touching the system, and returns plausible
    observations so the agent loop can be exercised end to end."""

    FAKE = {
        "list_windows": "Document1 - Word | WINWORD.EXE\nLazy-Monster | python.exe",
        "read_window": "window: Document1 - Word | WINWORD.EXE\nButton: File\nButton: Home\nDocument: Page 1",
        "read_text": "document in Untitled - Notepad:\n(dry-run text)",
        "write_in_app": "wrote text into Untitled - Notepad; verified: the document contains the text",
        "code_run": "main.py is running (pid 1234); its window should be open",
        "code_install": "installed pygame into snake_game/.venv",
        "open_file": "opened C:\\temp\\index.html in chrome",
        "draft_email": "opened an email draft titled 'Cafe website meeting'; the user reviews and sends it",
        "export_pdf": "saved and opened C:\\temp\\doc.pdf",
        "make_presentation": "built and opened C:\\temp\\deck.pptx",
    }

    def __init__(self, apps=None, writer=None):
        self.apps, self.calls, self.context = apps, [], ""
        self.owned = []                                   # tests put fake items here
        self.default_save_dir = "/tmp/lazymonster-test"
        self.saved, self.closed = [], []

    def owned_items(self):
        return list(self.owned)

    screen = {"title": "main.py - cafe - Visual Studio Code", "app": "Code.exe",
              "text": "TypeError: 'NoneType' object is not subscriptable", "image": None}

    def capture_screen(self):
        return dict(self.screen)

    def save_item(self, o, path):
        self.saved.append((o["label"], str(path)))
        return str(path)

    def close_item(self, o, discard_prompt=True):
        self.closed.append(o["label"])
        return f"closed {o['label']}"

    def run(self, intent):
        self.calls.append(intent)
        print(f"  [dry-run] {intent.name} {_brief(intent.args)}", flush=True)
        out = self.FAKE.get(intent.name, "dry-run")
        return True, out, out


def _brief(args):
    return {k: (v[:60] + "…" if isinstance(v, str) and len(v) > 60 else v) for k, v in args.items()}
