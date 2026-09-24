"""Text normalisation: lowercase, strip punctuation, spoken numbers -> digits."""
import re

_UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
          "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_FILLERS = re.compile(r"^(?:(?:please|can you|could you|would you|will you|kindly|just|um|uh)\s+)+")
_TRAIL = re.compile(r"(?:\s+(?:please|for me|now|thanks|thank you))+$")


def words_to_numbers(text: str) -> str:
    """'volume to twenty five percent' -> 'volume to 25 percent'."""
    out, i, toks = [], 0, text.split()
    while i < len(toks):
        t = toks[i]
        if t in _TENS:
            v = _TENS[t]
            if i + 1 < len(toks) and toks[i + 1] in _UNITS and 0 < _UNITS[toks[i + 1]] < 10:
                v += _UNITS[toks[i + 1]]
                i += 1
            out.append(str(v))
        elif t in _UNITS and t != "oh":
            out.append(str(_UNITS[t]))
        elif t == "hundred" and out and out[-1].isdigit():
            out[-1] = str(int(out[-1]) * 100)
        elif t == "hundred":
            out.append("100")
        else:
            out.append(t)
        i += 1
    return " ".join(out)


def normalize(text: str) -> str:
    t = text.lower().replace("%", " percent ")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = t.replace("'", "")
    t = re.sub(r"\s+", " ", t).strip()
    t = words_to_numbers(t)
    t = _FILLERS.sub("", t)
    t = _TRAIL.sub("", t)
    return t.strip()
