"""`monster wake-train`: build a personal "Hey Monster" detector on this PC.

Positives: your own recordings (weighted up) plus synthetic Kokoro voices in
many accents and speeds. Negatives: look-alike phrases ("hey mister", "a monster
movie"), ordinary commands, your own normal speech, and silence/room noise."""
import random
import time
from typing import List

import numpy as np

from .wakeword import CTX, Features, Head, Stream, model_path, pick_threshold, train_head

POS_TEXT = ["Hey Monster", "Hey, Monster.", "Hey monster!", "Hey Monster,", "Hey Monster?"]
HARD_NEG = ["hey mister", "hey master", "a monster movie", "hey man", "hey Mona", "hey Sister", "monsoon season",
            "honey bunny", "hey what's up", "my monster truck", "hey muster", "hello there", "okay Google",
            "hey Siri", "Alexa", "hey Mustafa", "the monsters are coming", "hey, mom stir it", "hey, Mister Monk"]
PLAIN_NEG = ["open notepad and type hello", "what time is it", "set the volume to thirty", "I'll be there in ten minutes",
             "can you send me that file", "the traffic in Bangalore is terrible today", "let's grab lunch at one",
             "please save the document", "turn off the lights", "that movie was really good", "we need more coffee",
             "the meeting got moved to Thursday", "did you see the match yesterday", "play some music",
             "I'm working on the presentation", "call me back when you're free"]
VOICES_ALL = ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "af_nova", "af_river", "af_jessica", "af_kore",
              "am_adam", "am_michael", "am_eric", "am_liam", "am_onyx", "am_puck", "bf_emma", "bf_alice", "bf_lily",
              "bm_george", "bm_lewis", "bm_daniel", "hf_alpha", "hf_beta", "hm_omega", "hm_psi"]


def _resample(x: np.ndarray, sr: int, to: int = 16000) -> np.ndarray:
    if sr == to:
        return x.astype(np.float32)
    n = int(len(x) * to / sr)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _noise(n: int, level: float) -> np.ndarray:
    return (np.random.randn(n) * level).astype(np.float32)


def _augment(x: np.ndarray) -> np.ndarray:
    peak = np.abs(x).max() or 1.0
    y = x / peak * random.uniform(0.25, 0.9)
    return (y + _noise(len(y), random.uniform(0.001, 0.01))).astype(np.float32)


def _windows(feats: Features, clip: np.ndarray, last: int = 0, skip: int = 6) -> List[np.ndarray]:
    """Feature windows for a clip, streamed exactly as at runtime."""
    s = Stream(feats)
    lead = _noise(16000, 0.002)
    out = [w.copy() for w in s.push(np.concatenate([lead, clip]))]
    out = out[skip:]
    return out[-last:] if last else out


def synth(kokoro, texts, voices, speeds=(0.9, 1.0, 1.12)) -> List[np.ndarray]:
    clips = []
    for v in voices:
        if v not in kokoro.get_voices():
            continue
        for t in texts:
            sp = random.choice(speeds)
            a, sr = kokoro.create(t, voice=v, speed=sp, lang="en-us")
            clips.append(_resample(np.asarray(a, dtype=np.float32), sr))
    return clips


def record_clips(n: int, seconds: float, prompt: str) -> List[np.ndarray]:
    import sounddevice as sd
    clips = []
    for i in range(n):
        input(f"  [{i + 1}/{n}] Press Enter, then {prompt}")
        a = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        clips.append(a[:, 0].copy())
    return clips


def trim(clip: np.ndarray, thresh: float = 0.02) -> np.ndarray:
    """Cut silence around a recorded phrase (20 ms frames)."""
    fr = 320
    e = [np.sqrt(np.mean(clip[i:i + fr] ** 2)) for i in range(0, max(len(clip) - fr, 1), fr)]
    idx = [i for i, v in enumerate(e) if v > thresh]
    if not idx:
        return clip
    return clip[max(0, idx[0] - 3) * fr:(idx[-1] + 4) * fr]


def build(kokoro, feats: Features, user_pos=(), user_neg=(), voices=None, log=print, seed: int = 7):
    random.seed(seed)
    np.random.seed(seed)
    voices = voices or [v for v in VOICES_ALL if v in kokoro.get_voices()]
    t0 = time.time()
    log(f"  synthesising wake phrases in {len(voices)} voices…")
    pos_clips = synth(kokoro, POS_TEXT, voices)
    log(f"  synthesising look-alike and everyday phrases…")
    neg_clips = synth(kokoro, HARD_NEG, voices[::2]) + synth(kokoro, PLAIN_NEG, voices[1::3])
    pos_clips += [trim(c) for c in user_pos for _ in range(4)]          # your voice counts more
    neg_clips += list(user_neg) + [_noise(32000, lvl) for lvl in (0.001, 0.005, 0.02)]
    log(f"  extracting features ({len(pos_clips)} positive, {len(neg_clips)} negative clips)…")
    pos, neg = [], []
    for c in pos_clips:
        tail = np.concatenate([_noise(random.randint(3000, 12000), 0.002), _augment(c), _noise(5600, 0.002)])
        pos += _windows(feats, tail, last=3)
    for c in neg_clips:
        neg += _windows(feats, np.concatenate([_augment(c), _noise(8000, 0.002)]))
    log(f"  features ready in {time.time() - t0:.0f} s: {len(pos)} positive, {len(neg)} negative windows")
    return np.array(pos), np.array(neg)


def fit(pos: np.ndarray, neg: np.ndarray, holdout: float = 0.2, seed: int = 7):
    rng = np.random.default_rng(seed)
    ip, ineg = rng.permutation(len(pos)), rng.permutation(len(neg))
    kp, kn = int(len(pos) * (1 - holdout)), int(len(neg) * (1 - holdout))
    head = train_head(pos[ip[:kp]], neg[ineg[:kn]])
    report = pick_threshold(head, pos[ip[kp:]], neg[ineg[kn:]])
    return head, report
