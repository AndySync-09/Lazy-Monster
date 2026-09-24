"""Wake-phrase spotting on the streaming transcript (no extra model).
Speech models sometimes hear 'Monster' as Monsta/Munster/Mobster, so close variants count."""
import re
from typing import Optional, Tuple

DEFAULT_NAMES = ["monster", "monsters", "monsta", "monstah", "munster", "mobster", "monstor", "lazy monster"]


class WakeSpotter:
    # "Hey" is often transcribed as "A", "Ay", "Eh" or "Hay".
    def __init__(self, names=None, prefixes=("hey", "hay", "hei", "a", "ay", "eh", "hi", "ok", "okay", "yo",
                                             "you", "me", "here", "hear", "him", "hmm", "hello"),
                 require_prefix=True):
        names = names or DEFAULT_NAMES
        n = "|".join(map(re.escape, names))
        p = "|".join(map(re.escape, prefixes))
        weak = ("a", "ay", "eh", "you", "me", "here", "hear", "him", "hmm")   # only count at line start
        strong = "|".join(re.escape(x) for x in prefixes if x not in weak)
        if require_prefix:
            # Line start: any prefix or none. Mid-sentence: only an unambiguous "hey/ok/...",
            # so "a movie about a monster" never wakes it.
            lead = rf"(?:^\s*(?:(?:{p})[\s,]+)?|\b(?:{strong})[\s,]+)"
        else:
            lead = rf"(?:^|\b)(?:(?:{p})[\s,]+)?"
        self.pat = re.compile(rf"{lead}(?:{n})\b[\s,.!?]*", re.I)

    def split(self, text: str) -> Tuple[bool, str]:
        """Returns (woke, command_after_wake). Uses the LAST wake occurrence."""
        last: Optional[re.Match] = None
        for m in self.pat.finditer(text):
            last = m
        if not last:
            return False, ""
        return True, text[last.end():].strip()
