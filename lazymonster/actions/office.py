"""Microsoft Word via COM (desktop Word + pywin32). Must be used from the agent
worker thread, which initialises COM once."""
from .files import out_dir, safe_name, unique_path


class WordSession:
    def __init__(self):
        self.word = None
        self.doc = None

    def _app(self):
        import win32com.client
        if self.word is None:
            self.word = win32com.client.Dispatch("Word.Application")
        self.word.Visible = True
        return self.word

    def new_document(self):
        self.doc = self._app().Documents.Add()
        try:
            self.word.Activate()
        except Exception:
            pass
        return "new Word document"

    def _current(self):
        try:
            if self.doc is not None:
                _ = self.doc.Name                     # raises if the user closed it
                return self.doc
        except Exception:
            self.doc = None
        app = self._app()
        self.doc = app.ActiveDocument if app.Documents.Count else app.Documents.Add()
        return self.doc

    def insert_text(self, text: str, words_per_tick: int = 5, delay: float = 0.03):
        """Writes in small chunks so you can watch it type."""
        import re
        import time
        doc = self._current()
        chunks = re.findall(r"\S+\s*", text.rstrip() + "\n")
        for i in range(0, len(chunks), words_per_tick):
            doc.Content.InsertAfter("".join(chunks[i:i + words_per_tick]))
            try:
                self.word.Selection.EndKey(6)       # wdStory: follow the text
            except Exception:
                pass
            time.sleep(delay)
        try:
            from ..textops import verify
            ok, note = verify(text, doc.Content.Text)
        except Exception:
            note = "could not read the document back"
        return f"inserted {len(text.split())} words; {note}"

    def save(self, filename: str):
        doc = self._current()
        path = unique_path(out_dir(), safe_name(filename, (".docx",), ".docx"))
        doc.SaveAs2(str(path), 16)                    # wdFormatDocumentDefault
        return f"saved {path}"
