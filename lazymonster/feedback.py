import os
import threading

TONES = {"ok": [(1320, 45)], "armed": [(880, 50)], "confirm": [(880, 60), (1175, 60)],
         "unknown": [(440, 90)], "error": [(330, 140)], "cancelled": [(660, 60), (440, 60)], "thinking": [(990, 40)], "followup": []}
LABEL = {"ok": "done", "armed": "listening…", "confirm": "say 'yes' to confirm",
         "unknown": "didn't catch a command", "error": "failed", "cancelled": "cancelled", "thinking": "working…", "followup": "listening for a follow-up (15 s)…"}


def make_feedback(beeps: bool = True):
    def fb(kind: str) -> None:
        print(f"  · {LABEL.get(kind, kind)}", flush=True)
        if False:                                   # sounds now come from conversation.py (three earcons only)
            import winsound

            def play():
                for f, d in TONES.get(kind, []):
                    winsound.Beep(f, d)
            threading.Thread(target=play, daemon=True).start()
    return fb
