import json

import pytest

from lazymonster.actions.dryrun import DryRunExecutor
from lazymonster.actions.files import safe_name, unique_path
from lazymonster.apps import AppIndex
from lazymonster.engine import Engine
from lazymonster.grammar import Grammar
from lazymonster.intents import Intent, SchemaError, validate
from lazymonster.normalize import normalize
from lazymonster.agent import Agent, tool_specs
from lazymonster.guards import GuardError, check_click, check_input_target, parse_keys, safe_rel_path
from lazymonster.wake import WakeSpotter
from lazymonster.worker import Worker


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class FakeWriter:
    def generate(self, prompt, max_words):
        return f"STORY about {prompt}"


def make(**kw):
    apps = AppIndex(scan_start_menu=False)
    ex, clock, fb = DryRunExecutor(apps), Clock(), []
    logs = []
    worker = Worker(ex, lambda **k: logs.append(k), synchronous=True, clock=clock)
    eng = Engine(Grammar(apps.resolve), WakeSpotter(), worker, feedback=fb.append,
                 clock=clock, logger=logs.append, **kw)
    return eng, ex, clock, fb, logs


# ---- lane 1: instant ---------------------------------------------------------
def test_normalize_numbers_and_fillers():
    assert normalize("Could you set the volume to Twenty-Five %, please?") == "set the volume to 25 percent"


def test_early_fire_after_stable_partials():
    eng, ex, *_ = make()
    eng.on_partial(1, "Hey Monster, mute")
    assert ex.calls == []
    eng.on_partial(1, "Hey Monster, mute")
    assert ex.calls == [Intent.make("mute")]
    eng.on_complete(1, "Hey Monster, mute.")
    assert len(ex.calls) == 1


def test_changing_partial_resets_stability():
    eng, ex, *_ = make()
    eng.on_partial(1, "hey monster set volume to 20")
    eng.on_partial(1, "hey monster set volume to 25")
    assert ex.calls == []
    eng.on_partial(1, "hey monster set volume to 25")
    assert ex.calls == [Intent.make("volume_set", level=25)]


def test_open_app_never_fires_early():
    """'open word' is often the start of 'open word and write a story'."""
    eng, ex, *_ = make()
    for _ in range(5):
        eng.on_partial(1, "hey monster open word")
    assert ex.calls == []
    eng.on_complete(1, "hey monster open word")
    assert ex.calls == [Intent.make("open_app", app="word")]


def test_compound_request_never_fires_early():
    eng, ex, *_ = make()
    for _ in range(5):
        eng.on_partial(1, "hey monster mute and then")
    assert ex.calls == []


def test_no_wake_no_action():
    eng, ex, *_ = make()
    eng.on_partial(1, "mute"); eng.on_partial(1, "mute"); eng.on_complete(1, "mute")
    eng.on_complete(2, "jeff said to open chrome")
    assert ex.calls == []


def test_wake_then_pause_then_command():
    eng, ex, clock, fb, _ = make()
    eng.on_complete(1, "Hey Monster.")
    assert "armed" in fb
    clock.t = 2.0
    eng.on_complete(2, "open chrome")
    assert ex.calls == [Intent.make("open_app", app="chrome")]
    clock.t = 20.0
    eng.on_complete(3, "open notepad")
    assert len(ex.calls) == 1


def test_destructive_needs_confirmation():
    eng, ex, clock, fb, _ = make()
    eng.on_complete(1, "hey monster shut down the computer")
    assert ex.calls == [] and "confirm" in fb
    eng.on_complete(2, "yes")
    assert ex.calls == [Intent.make("shutdown")]


def test_confirmation_expires_and_no_cancels():
    eng, ex, clock, fb, _ = make()
    eng.on_complete(1, "hey monster restart")
    eng.on_complete(2, "no")
    assert ex.calls == [] and fb[-1] == "cancelled"
    eng.on_complete(3, "hey monster restart")
    clock.t = 30.0
    eng.on_complete(4, "yes")
    assert ex.calls == []


def test_no_brain_says_so_once():
    eng, ex, _, fb, logs = make()
    spoken = []
    eng.say = spoken.append
    eng.on_complete(1, "hey monster open the pod bay doors")
    eng.on_complete(2, "hey monster write me a poem")
    assert ex.calls == [] and len(spoken) == 1 and "brain" in spoken[0]


# ---- lane 2: agent loop -----------------------------------------------------------
class ScriptedClient:
    """Returns a scripted sequence of tool calls, one per chat() call."""
    def __init__(self, turns): self.turns, self.seen = list(turns), []
    def chat(self, messages, tools=None):
        self.seen = list(messages)
        calls = self.turns.pop(0)
        if isinstance(calls, str):
            return {"choices": [{"message": {"role": "assistant", "content": calls}}]}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)]}}]}


def make_agent(turns):
    eng, ex, clock, fb, logs = make()
    said = []
    client = ScriptedClient(turns)
    eng.worker.agent = Agent(client, ex, lambda **k: logs.append(k), said.append, clock=clock)
    eng.agent_enabled = True
    return eng, ex, client, said, fb


def test_agent_writes_word_story():
    eng, ex, client, said, fb = make_agent([
        [("word_new_document", {})],
        [("word_insert_text", {"text": "Once upon a time, Jev Engineering..."})],
        [("word_save", {"filename": "JevStory"})],
        [("finish", {"summary": "Saved JevStory.docx"})]])
    eng.on_complete(1, "hey monster open word and write a story about jev engineering and save it")
    assert [c.name for c in ex.calls] == ["word_new_document", "word_insert_text", "word_save"]
    assert said == ["Saved JevStory.docx"] and "ok" in fb


def test_agent_writes_code_in_vscode():
    eng, ex, client, said, fb = make_agent([
        [("code_open", {"project": "snake"})],
        [("code_write_file", {"project": "snake", "path": "snake.py", "content": "print('snake')\n"})],
        [("finish", {"summary": "Wrote snake.py"})]])
    eng.on_complete(1, "hey monster open vs code and write a snake game in python")
    assert [c.name for c in ex.calls] == ["code_open", "code_write_file"]


def test_agent_gets_errors_back_instead_of_running_bad_calls():
    eng, ex, client, said, fb = make_agent([
        [("run_shell", {"cmd": "format c:"}), ("volume_set", {"level": 500})],
        [("shutdown", {})],
        "I can't do that safely."])
    eng.on_complete(1, "hey monster wipe my disk")
    assert ex.calls == []
    tool_msgs = [m for m in client.seen if m.get("role") == "tool"]
    assert all(m["content"].startswith("ERROR") for m in tool_msgs) and len(tool_msgs) == 3
    assert said == ["I can't do that safely."]


def test_agent_tool_list_excludes_confirm_and_internal():
    names = {t["function"]["name"] for t in tool_specs()}
    assert {"shutdown", "restart", "sleep", "confirm_yes"}.isdisjoint(names)
    assert {"code_write_file", "click", "read_window", "finish"} <= names


def test_stop_cancels_agent():
    eng, ex, *_ = make_agent([[("list_windows", {})]])
    eng.on_complete(9, "hey monster stop")
    assert eng.worker.agent.cancel.is_set()


def test_step_limit():
    eng, ex, client, said, fb = make_agent([[("list_windows", {})]] * 40)
    eng.worker.agent.max_steps = 3
    eng.on_complete(1, "hey monster do something forever")
    assert len(ex.calls) == 3 and "step limit" in said[-1]


# ---- guards -----------------------------------------------------------------------
@pytest.mark.parametrize("proc", ["cmd.exe", "PowerShell.exe", "WindowsTerminal.exe", "Code.exe", "consent.exe", "KeePass.exe"])
def test_input_blocked_for_shells_and_credentials(proc):
    with pytest.raises(GuardError):
        check_input_target(proc)


def test_input_allowed_for_normal_apps():
    check_input_target("notepad.exe"); check_input_target("WINWORD.EXE"); check_input_target("chrome.exe")


@pytest.mark.parametrize("name", ["Delete", "Send", "Pay now", "Buy", "Uninstall", "Empty Recycle Bin", "End task", "Install"])
def test_risky_clicks_blocked(name):
    with pytest.raises(GuardError):
        check_click(name, "chrome.exe")


def test_safe_clicks_allowed():
    check_click("Save", "WINWORD.EXE"); check_click("New tab", "chrome.exe"); check_click("Bold", "WINWORD.EXE")


@pytest.mark.parametrize("keys", ["win+r", "win+x", "ctrl+`", "alt+f4", "shift+delete", "ctrl+alt+t", "win+e", "f12", "ctrl+ctrl+s"])
def test_banned_keys(keys):
    with pytest.raises(GuardError):
        parse_keys(keys)


def test_allowed_keys():
    assert parse_keys("Ctrl + S") == ["ctrl", "s"]
    assert parse_keys("enter") == ["enter"]
    assert parse_keys("win+d") == ["win", "d"]


@pytest.mark.parametrize("path", ["../x.py", "C:/Windows/x.py", "/etc/x.py", "a/../../b.py", "run.bat", "x.ps1", "evil.exe", "a/b.lnk"])
def test_bad_code_paths(path):
    with pytest.raises(GuardError):
        safe_rel_path(path)


def test_good_code_paths():
    assert safe_rel_path("src\\app.py") == "src/app.py"
    assert safe_rel_path("index.html") == "index.html"


# ---- sandbox & schema -----------------------------------------------------------
def test_safe_names(tmp_path):
    assert safe_name("..\\..\\Windows\\evil.exe", (".txt", ".md"), ".txt") == "evil.exe.txt"
    assert safe_name("My Story", (".docx",), ".docx") == "My Story.docx"
    (tmp_path / "a.txt").write_text("x")
    assert unique_path(tmp_path, "a.txt").name == "a (2).txt"


def test_validate_types():
    assert validate("volume_up", {}).name == "volume_up"
    with pytest.raises(SchemaError):
        validate("volume_set", {"level": True})
    with pytest.raises(SchemaError):
        validate("code_write_file", {"project": "p", "path": "a.py"})


@pytest.mark.parametrize("text", ["A monster.", "Hay monster, mute", "Monster, mute", "hey monster mute", "eh monster mute"])
def test_wake_variants(text):
    assert WakeSpotter().split(text)[0]


@pytest.mark.parametrize("text", ["I saw a movie about a monster", "that monster truck was loud"])
def test_no_wake_mid_sentence_without_prefix(text):
    assert not WakeSpotter().split(text)[0]


def test_a_monster_then_command_line():
    eng, ex, clock, fb, _ = make()
    eng.on_complete(1, "A monster.")
    clock.t = 3.0
    eng.on_complete(2, "Open notepad")
    assert ex.calls == [Intent.make("open_app", app="notepad")]


def test_cancel_it_stops_agent():
    eng, ex, *_ = make()
    class A:
        import threading
        cancel = threading.Event()
    eng.worker.agent = A()
    eng.on_complete(1, "hey monster cancel it")
    assert A.cancel.is_set()


def test_followup_without_wake_uses_same_session():
    eng, ex, client, said, fb = make_agent([
        [("open_app", {"app": "notepad"})], [("type_text", {"text": "hello"})], [("finish", {"summary": "typed"})],
        [("press_keys", {"keys": "ctrl+s"})], [("finish", {"summary": "saved"})]])
    eng.on_complete(1, "hey monster open notepad and type hello")
    assert "followup" in fb
    eng.on_complete(2, "can you save it")                    # no wake phrase
    assert [c.name for c in ex.calls] == ["open_app", "type_text", "press_keys"]
    users = [m["content"] for m in client.seen if m.get("role") == "user"]
    assert users == ["open notepad and type hello", "can you save it"]   # history carried over
    assert said[-1] == "saved"


def test_followup_window_expires():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.on_complete(1, "hey monster open notepad and type hello")
    eng.clock.t = 100.0
    eng.on_complete(2, "can you save it")
    assert len(client.turns) == 0 and said == ["ok"]


def test_click_slot_named_name_validates():
    i = validate("click", {"name": "Save"}, source="agent", allow_refs=False)
    assert i.name == "click" and i.args == {"name": "Save"}


def test_agent_clicks_dialog_button():
    eng, ex, client, said, fb = make_agent([
        [("click", {"name": "Save", "window": "Notepad"})], [("finish", {"summary": "saved"})]])
    eng.on_complete(1, "hey monster save it")
    assert ex.calls == [Intent.make("click", source="agent", name="Save", window="Notepad")]


def test_close_app_resolves_display_name():
    apps = AppIndex(scan_start_menu=False)
    assert apps.resolve("Notepad") == "notepad"


@pytest.mark.parametrize("text", ["hey monster sleep", "hey monster exit", "hey monster go to sleep", "hey monster goodnight"])
def test_sleep_exits(text):
    exited = []
    eng, ex, *_ = make(on_exit=lambda: exited.append(1))
    eng.on_complete(1, text)
    assert exited == [1] and ex.calls == []


def test_pc_sleep_needs_explicit_words_and_confirmation():
    eng, ex, clock, fb, _ = make()
    eng.on_complete(1, "hey monster put the computer to sleep")
    assert "confirm" in fb and ex.calls == []


def test_ask_user_waits_for_spoken_answer():
    import threading
    eng, ex, client, said, fb = make_agent([
        [("ask_user", {"question": "Save or don't save?"})],
        [("click", {"name": "Save"})], [("finish", {"summary": "saved"})]])
    agent = eng.worker.agent
    threading.Timer(0.05, lambda: agent.hear("save it")).start()
    assert agent.run("close notepad")
    assert said[0] == "Save or don't save?" and ex.calls == [Intent.make("click", source="agent", name="Save")]
    tool_results = [m["content"] for m in client.seen if m.get("role") == "tool"]
    assert tool_results[0] == "The user answered: save it"


def test_speech_during_task_goes_to_agent():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "x"})]])
    eng.worker.busy.set()
    eng.on_complete(5, "save it")
    assert eng.worker.agent.inbox.get_nowait() == "save it"
    eng.worker.busy.clear()


# ---- 0.3.0: interactive + ownership --------------------------------------------------
from lazymonster.guards import check_type_target, is_editing, is_sensitive, owns, redact_title


def test_recovery_codes_window_is_sensitive():
    t = "*PyPI-Recovery-Codes-memforkdb-2026-09-21T04_11_16.998482.txt - Notepad"
    assert is_sensitive(t) and redact_title(t) == "[sensitive window]"
    with pytest.raises(GuardError):
        check_type_target(t, "open notepad and type hello")


@pytest.mark.parametrize("title", ["Untitled - Notepad", "*Untitled - Notepad", "Document1 - Word", "New Tab - Google Chrome"])
def test_new_documents_are_owned(title):
    check_type_target(title, "type hello")


def test_existing_document_needs_to_be_named():
    with pytest.raises(GuardError):
        check_type_target("meeting notes.txt - Notepad", "open notepad and type hello")
    check_type_target("meeting notes.txt - Notepad", "add a line to my meeting notes")


def test_editing_keys_classified():
    assert is_editing(["enter"]) and is_editing(["ctrl", "v"]) and is_editing(["a"])
    assert not is_editing(["ctrl", "n"]) and not is_editing(["ctrl", "s"]) and not is_editing(["tab"])


def test_finish_speaks_summary_and_offer_then_yes_runs_it():
    eng, ex, client, said, fb = make_agent([
        [("type_text", {"text": "hello"})],
        [("finish", {"summary": "Typed hello.", "next": "Want me to save it?"})],
        [("press_keys", {"keys": "ctrl+s"})], [("finish", {"summary": "Saved."})]])
    eng.on_complete(1, "hey monster open notepad and type hello")
    assert said[-1] == "Typed hello. Want me to save it?"
    eng.on_complete(2, "yes")                                  # in the follow-up window
    assert ex.calls[-1].name == "press_keys" and said[-1] == "Saved."


def test_no_to_offer_moves_on():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Done.", "next": "Want me to save it?"})]])
    eng.on_complete(1, "hey monster make me a haiku")
    eng.say = said.append
    eng.on_complete(2, "no")
    assert said[-1] == "Okay. What next?" and eng.worker.agent.suggestion == ""


def test_two_failures_force_a_question():
    class Failing(DryRunExecutor):
        def run(self, intent):
            self.calls.append(intent)
            return False, "nope", None
    eng, ex, client, said, fb = make_agent([[("list_windows", {})], [("list_windows", {})],
                                            [("finish", {"summary": "x"})]])
    eng.worker.agent.ex = Failing()
    eng.on_complete(1, "hey monster do the thing")
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"]
    assert "ask_user" in tool[1]


def test_long_command_after_wake_counts_from_line_start():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.on_complete(1, "Hey monster")                 # armed until t=8
    eng.clock.t = 3.0
    eng.on_partial(2, "Open notepad and")             # line starts inside the window
    eng.clock.t = 12.0                                # ...and finishes after it
    eng.on_complete(2, "Open notepad and write a haiku about bangalore traffic")
    assert "thinking" in fb and said == ["ok"]


@pytest.mark.parametrize("text", ["You monster.", "Me monster.", "Here, monster."])
def test_more_wake_mishearings(text):
    assert WakeSpotter().split(text)[0]


def test_weak_prefix_mid_sentence_does_not_wake():
    assert not WakeSpotter().split("I told you monster trucks are loud")[0]


# ---- 0.4.0 ---------------------------------------------------------------------------
from lazymonster.textops import paste_lines, verify, parse_candidates, sentences
from lazymonster.stt_refine import strip_wake_lead


def test_refined_transcript_replaces_fast_one():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.refine = lambda t0: "Hey Monster, open Notepad and write a haiku about Bangalore traffic."
    eng.refine_async = False
    logs = []
    eng.logger = logs.append
    eng.on_complete(1, "A monster open notepad and write a haiku about value traffic")
    users = [m["content"] for m in client.seen if m.get("role") == "user"]
    assert users == ["open Notepad and write a haiku about Bangalore traffic."]
    assert any('"refined"' in l for l in logs)


def test_refine_failure_falls_back_to_fast_text():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    def boom(t0): raise RuntimeError("npu busy")
    eng.refine, eng.refine_async = boom, False
    eng.on_complete(1, "hey monster open notepad and write a haiku")
    assert [m["content"] for m in client.seen if m.get("role") == "user"] == ["open notepad and write a haiku"]


def test_strip_wake_lead_variants():
    assert strip_wake_lead("Hey, Monster. Open Word") == "Open Word"
    assert strip_wake_lead("A monster open notepad") == "open notepad"
    assert strip_wake_lead("open notepad") == "open notepad"


def test_paste_lines_and_verify():
    assert paste_lines("a\r\nb\n\nc") == ["a", "b", "", "c"]
    ok, _ = verify("Bangalore roads sigh\nHorns bloom", "bangalore roads sigh horns bloom\r\n")
    assert ok
    ok, msg = verify("Bangalore roads sigh", "Bangalore sssssssssssss")
    assert not ok and "MISMATCH" in msg


def test_candidates_parsing():
    c = parse_candidates('thinking {"candidates":[{"tool":"write_in_app","p":0.8},{"tool":"open_app","p":"0.2"}]}')
    assert c == [{"tool": "write_in_app", "p": 0.8}, {"tool": "open_app", "p": 0.2}]
    assert parse_candidates(None) == [] and parse_candidates("no json here") == []


def test_agent_logs_candidates_and_hides_them_from_speech():
    class C(ScriptedClient):
        def chat(self, messages, tools=None):
            r = super().chat(messages, tools)
            m = r["choices"][0]["message"]
            if m.get("tool_calls"):
                m["content"] = '{"candidates":[{"tool":"write_in_app","p":0.9}]}'
            return r
    eng, ex, client, said, fb = make_agent([])
    logs = []
    eng.worker.agent.client = C([[("write_in_app", {"app": "notepad", "text": "hi"})], "All done."])
    eng.worker.agent.log = lambda **k: logs.append(k)
    eng.on_complete(1, "hey monster write hi in notepad please")
    thinks = [l for l in logs if l.get("event") == "agent_think"]
    assert thinks[0]["candidates"][0]["tool"] == "write_in_app" and thinks[0]["chosen"] == ["write_in_app"]
    assert said == ["All done."]


def test_sentences_split_for_streaming_speech():
    assert sentences("Done. Want me to save it? Sure!") == ["Done.", "Want me to save it?", "Sure!"]


def test_ui_bus_maps_engine_signals_to_page_events():
    import json as _j
    from lazymonster.ui.app import UIBus
    bus = UIBus()
    sent = []
    bus._send = sent.append
    bus.ready.set()
    bus.feedback("armed")
    bus.log(_j.dumps({"event": "agent_think", "candidates": [{"tool": "write_in_app", "p": .8}], "chosen": ["write_in_app"]}))
    bus.log(_j.dumps({"event": "step", "intent": "type_text", "ok": False, "msg": "{} -> GuardError: sensitive"}))
    bus.feedback("ok")
    kinds = [e["type"] for e in sent]
    assert kinds == ["decide", "step", "done"]              # screen state now comes from conversation.py
    assert sent[1]["blocked"] is True and sent[0]["chosen"] == ["write_in_app"]


def test_typed_text_skips_audio_refine():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.refine = lambda t0: (_ for _ in ()).throw(AssertionError("should not re-hear typed text"))
    eng.refine_async = False
    eng.handle_text("open notepad and write a haiku")
    assert [m["content"] for m in client.seen if m.get("role") == "user"] == ["open notepad and write a haiku"]


def test_ui_api_exposes_only_three_methods():
    from lazymonster.ui.app import Api
    api = Api(engine=object(), stop=None, bus=None)
    assert [n for n in dir(api) if not n.startswith("_")] == ["compact", "get_settings", "hide", "list_models", "preview_voice", "retrain_voice", "set_key", "set_setting", "sleep", "stop_talking", "submit", "talk", "test_brain", "ui_busy"]


# ---- 0.5.0 ---------------------------------------------------------------------------
def test_wake_arms_listening_window():
    eng, ex, clock, fb, logs = make()
    eng.wake_up()
    assert "armed" in fb
    clock.t = 3.0
    eng.on_complete(5, "open notepad")                   # no wake phrase needed after the NPU wake
    assert ex.calls == [Intent.make("open_app", app="notepad")]


def test_engine_busy_reflects_activity():
    eng, ex, clock, fb, logs = make()
    clock.t = 100.0
    assert not eng.busy()
    eng.wake_up()
    assert eng.busy()


def test_mic_gate_reasons():
    from lazymonster.stt import MicGate
    class Mic:
        muted = None
        def mute(self, m): Mic.muted = m
    g = MicGate(); g.mic = Mic()
    g.set("idle", True); assert Mic.muted is True
    g.set("speaking", True); g.set("idle", False); assert Mic.muted is True
    g.set("speaking", False); assert Mic.muted is False


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster.config import Config, save_setting
    save_setting("kokoro_voice", "bf_emma")
    save_setting("wake_sensitivity", 0.1)
    cfg = Config.load(str(tmp_path / "nope.toml"))
    assert cfg.kokoro_voice == "bf_emma" and cfg.wake_sensitivity == 0.1


def test_wake_head_learns_and_picks_threshold():
    import numpy as np
    from lazymonster.wakeword import pick_threshold, train_head
    rng = np.random.default_rng(0)
    pos = rng.normal(1.0, 1.0, (60, 16, 96)).astype("float32")
    neg = rng.normal(-1.0, 1.0, (400, 16, 96)).astype("float32")
    head = train_head(pos[:40], neg[:300])
    rep = pick_threshold(head, pos[40:], neg[300:])
    assert rep["recall"] >= 0.95 and rep["false_positive_rate"] <= 0.01 and 0.5 <= rep["threshold"] <= 0.95


def test_speaker_interrupt_sets_cancel():
    from lazymonster.tts import KokoroVoice, Speaker
    s = Speaker("off")
    s.kokoro = KokoroVoice()
    s.interrupt()
    assert s.kokoro.cancel.is_set()


# ---- 0.5.1: running code ------------------------------------------------------------
def test_code_run_needs_spoken_yes():
    import threading
    eng, ex, client, said, fb = make_agent([
        [("code_run", {"project": "snake", "path": "main.py"})], [("finish", {"summary": "running"})]])
    agent = eng.worker.agent
    threading.Timer(0.05, lambda: agent.hear("yes please")).start()
    agent.run("run the game")
    assert said[0] == "Run main.py from snake now?" and ex.calls[-1].name == "code_run"


def test_code_run_refused_without_yes():
    import threading
    eng, ex, client, said, fb = make_agent([
        [("code_install", {"project": "snake", "packages": "pygame"})], [("finish", {"summary": "ok"})]])
    agent = eng.worker.agent
    threading.Timer(0.05, lambda: agent.hear("no, not now")).start()
    agent.run("install pygame")
    assert ex.calls == []
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"]
    assert "did not approve" in tool[0]


@pytest.mark.parametrize("spec", ["pygame", "numpy==2.1.0", "requests[socks]", "pygame numpy"])
def test_safe_packages_ok(spec):
    from lazymonster.guards import safe_packages
    assert safe_packages(spec)


@pytest.mark.parametrize("spec", ["--index-url http://evil x", "git+https://x/y", "../local", "-e .", "a;b", ""])
def test_safe_packages_rejects(spec):
    from lazymonster.guards import safe_packages
    with pytest.raises(GuardError):
        safe_packages(spec)


def test_code_run_only_runs_files_it_wrote(tmp_path, monkeypatch):
    import lazymonster.actions.code as code
    monkeypatch.setattr(code, "code_root", lambda: tmp_path)
    monkeypatch.setattr(code.CodeWorkspace, "_launch", lambda self, *a: None)
    monkeypatch.setattr(code, "project_python", lambda folder: __import__("sys").executable)
    monkeypatch.setattr(code.time, "sleep", lambda s: None)
    ws = code.CodeWorkspace(stream_delay=0)
    ws.opened.add(str(tmp_path / "demo"))
    ws.write("demo", "main.py", "print('hi')\n")
    ok, msg = ws.run("demo", "main.py", wait=1.0)
    assert ok, msg
    (tmp_path / "demo" / "main.py").write_text("import os; os.remove('x')\n")      # tampered
    with pytest.raises(GuardError):
        ws.run("demo", "main.py")
    (tmp_path / "demo" / "other.py").write_text("print(1)\n")                     # not written by the monster
    with pytest.raises(GuardError):
        ws.run("demo", "other.py")


def test_npu_friendly_rewrite_is_exact():
    import numpy as np
    import openvino as ov
    import openvino.opset13 as ops
    from lazymonster.wakeword import npu_friendly
    x = ops.parameter([1, 64], np.float32, name="x")
    y = ops.parameter([1, 64], np.float32, name="y")
    out = ops.minimum(ops.maximum(ops.maximum(x, ops.constant(np.float32(1e-10))), y), ops.constant(np.float32(np.inf)))
    m = ov.Model([out], [x, y], "t")
    ref = ov.Core().compile_model(m.clone(), "CPU")
    new = npu_friendly(m)
    assert not [o for o in new.get_ops() if o.get_type_name() in ("Maximum", "Minimum")]
    got = ov.Core().compile_model(new, "CPU")
    a, b = np.random.randn(1, 64).astype(np.float32), np.random.randn(1, 64).astype(np.float32)
    assert np.allclose(list(ref([a, b]).values())[0], list(got([a, b]).values())[0], rtol=1e-6, atol=1e-6)


def test_whisper_warmup_shrinks_prompt_until_it_fits():
    from lazymonster.stt_refine import WhisperRefiner
    r = WhisperRefiner(vocabulary=["Koramangala"] * 5)
    seen = []

    class Pipe:
        def generate(self, samples, **kw):
            words = len(kw["initial_prompt"].split(",")) if "initial_prompt" in kw else 0
            seen.append(words)
            assert kw.get("max_new_tokens") == 96
            if words > 12:
                raise RuntimeError("Check '*roi_end <= *max_dim' failed")
            class R: texts = ["ok"]
            return R()
    r.pipe = Pipe()
    r._warm()
    assert r.prompt_words == 12 and seen[0] > 12


# ---- 0.6.0: conversation ------------------------------------------------------------
def test_turn_joins_lines_split_by_pauses():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.turn_delay = 0.9
    eng.on_complete(1, "Hey Monster.")                      # wake, pause
    eng.clock.t = 1.0
    eng.on_complete(2, "Open.")                             # "Open." alone would have been rejected
    eng.clock.t = 1.5
    eng.on_complete(3, "a snake game in Visual Studio.")
    eng.poll()
    assert client.seen == []                                # still inside the turn
    eng.clock.t = 2.6
    eng.poll()
    users = [m["content"] for m in client.seen if m.get("role") == "user"]
    assert users == ["Open. a snake game in Visual Studio."]


def test_instant_command_across_a_pause():
    eng, ex, *_ = make_agent([])
    eng.turn_delay = 0.9
    eng.on_complete(1, "Hey Monster, open")
    eng.clock.t = 0.5
    eng.on_complete(2, "notepad")
    assert ex.calls == [Intent.make("open_app", app="notepad")]


def test_one_word_answer_goes_to_agent_mid_conversation():
    eng, ex, client, said, fb = make_agent([
        [("finish", {"summary": "What game?", "next": ""})], [("finish", {"summary": "Snake it is."})]])
    eng.on_complete(1, "hey monster make me a game")
    eng.on_complete(2, "Snake.")                            # follow-up window, one word
    assert said[-1].startswith("Snake it is.")


def test_one_word_noise_ignored_when_idle():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "x"})]])
    eng.clock.t = 500.0
    eng.handle_text  # noqa
    eng.always_listen = True
    eng.on_complete(1, "Hmm.")
    assert client.seen == [] and fb[-1] == "unknown"


class _Spk:
    speaking = False
    def __init__(self): self.said, self.stopped = [], 0
    def say(self, t): self.said.append(t)
    def interrupt(self): self.stopped += 1


def _conv(eng, **kw):
    from lazymonster.conversation import Conversation
    from lazymonster.stt import MicGate
    events = []
    c = Conversation(eng, _Spk(), MicGate(), emit=events.append, chimes=False, speak_acks=False, clock=eng.clock, **kw)
    return c, events


def test_conversation_wake_rules():
    from lazymonster import conversation as C
    eng, ex, *_ = make()
    c, events = _conv(eng)
    eng.feedback = c.feedback
    c.on_wake(0.99)
    assert c.state == C.LISTENING
    c.on_wake(0.99)                                         # already listening: nothing, no re-arm spam
    assert [e["state"] for e in events if e["type"] == "state"] == ["listen"]
    c.set(C.SPEAKING); c.spoke_at = eng.clock.t
    c.on_wake(0.99)                                         # its own first words: ignored
    assert c.speaker.stopped == 0
    eng.clock.t += 2
    c.on_wake(0.96)                                         # real barge-in
    assert c.speaker.stopped == 1 and c.state == C.LISTENING


def test_conversation_mic_gate_follows_state():
    from lazymonster import conversation as C
    eng, *_ = make()
    c, _ = _conv(eng, wake_model=True)
    assert c.gate.has("idle")                               # sleeping: NPU listens, CPU transcriber paused
    c.set(C.LISTENING)
    assert not c.gate.has("idle")


def test_vs_code_title_not_sensitive():
    from lazymonster.guards import is_sensitive
    assert not is_sensitive("main.py - snake_game - Visual Studio Code")
    assert is_sensitive("PyPI-Recovery-Codes.txt - Notepad") and is_sensitive("github 2fa codes.txt")


def test_project_venvs_live_outside_onedrive(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from lazymonster.actions.code import venv_dir
    from pathlib import Path
    assert str(venv_dir(Path("C:/Users/x/OneDrive/Documents/LazyMonster/code/snake"))).startswith(str(tmp_path))


# ---- 0.7.0: background + greeting -------------------------------------------------------
@pytest.mark.parametrize("display,user,expected", [
    ("Annatam Dey", "andy0", "Annatam"), ("", "andy0", "Andy"), ("", "andy.dey", "Andy"),
    ("CORP\\\\jsmith", "", "Jsmith"), ("", "", ""), ("priya@outlook.com", "", "Priya")])
def test_first_name(display, user, expected):
    from lazymonster.userinfo import first_name
    assert first_name(display, user) == expected


def test_greets_after_a_bare_wake_but_not_over_you():
    from lazymonster import conversation as C
    eng, *_ = make()
    c, events = _conv(eng, user_name="Andy")
    eng.feedback = c.feedback
    c.greet = False                                          # drive the greeting by hand (no timers in tests)
    eng.wake_up()
    eng.clock.t += 0.7
    c._maybe_greet()
    assert c.speaker.said and "Andy" in c.speaker.said[-1]
    said_before = len(c.speaker.said)
    c.set(C.SLEEPING)
    eng.wake_up()
    eng.on_partial(99, "open notepad")                        # you kept talking after the wake word
    eng.clock.t += 0.7
    c._maybe_greet()
    assert len(c.speaker.said) == said_before


def test_background_launcher_is_windowless_and_background():
    from lazymonster.service import launcher
    cmd = launcher()
    assert "--background" in cmd and ("monsterw" in cmd or "pythonw" in cmd)


# ---- 0.8.0: close everything, save where you say, recap ------------------------------------
@pytest.mark.parametrize("answer,expect", [
    ("", ("save", "C:/temp", "haiku.txt")),
    ("yes", ("save", "C:/temp", "haiku.txt")),
    ("save it as bangalore poem", ("save", "C:/temp", "bangalore-poem")),
    ("call it grocery list on the desktop", ("save", "Desktop", "grocery-list")),
    ("no, don't save", ("discard", None, None)),
])
def test_save_answer_interpretation(answer, expect):
    from lazymonster.savepaths import interpret
    action, p = interpret(answer, "haiku.txt", "C:/temp")
    assert action == expect[0]
    if p is not None:
        assert expect[1] in str(p).replace("\\\\", "/") and p.name == expect[2]


def test_close_all_asks_about_unsaved_and_saves_where_told():
    import threading
    eng, ex, client, said, fb = make_agent([[("close_all", {})], [("finish", {"summary": "All closed."})]])
    ex.owned = [{"kind": "window", "label": "Notepad (haiku)", "dirty": True, "suggest": "haiku.txt"},
                {"kind": "proc", "label": "main.py from snake", "dirty": False}]
    agent = eng.worker.agent
    threading.Timer(0.05, lambda: agent.hear("save it as bangalore poem")).start()
    agent.run("close everything")
    assert said[0].startswith("Notepad (haiku) has unsaved changes")
    assert ex.saved and ex.saved[0][1].endswith("bangalore-poem.txt")
    assert ex.closed == ["Notepad (haiku)", "main.py from snake"]


def test_close_all_with_no_answer_saves_to_default_folder():
    eng, ex, client, said, fb = make_agent([[("close_all", {})], [("finish", {"summary": "Done."})]])
    ex.owned = [{"kind": "window", "label": "Notepad (note)", "dirty": True, "suggest": "note.txt"}]
    eng.worker.agent.ask_timeout = 0.05
    eng.worker.agent.run("close everything")
    assert ex.saved[0][1].replace("\\\\", "/").startswith("/tmp/lazymonster-test/note")


def test_close_all_discard():
    import threading
    eng, ex, client, said, fb = make_agent([[("close_all", {})], [("finish", {"summary": "Done."})]])
    ex.owned = [{"kind": "window", "label": "Notepad (x)", "dirty": True, "suggest": "x.txt"}]
    threading.Timer(0.05, lambda: eng.worker.agent.hear("no")).start()
    eng.worker.agent.run("close everything")
    assert ex.saved == [] and ex.closed == ["Notepad (x)"]


def test_journal_recap_and_context(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster import journal
    journal.add("Hey Monster, can you make a snake game in VS Code", "Done. I built a snake game in VS Code. Want to run it?",
                ["C:\\x\\main.py"], tools=["code_write_file"])
    journal.add("write a haiku about Bangalore traffic in Notepad", "Wrote a haiku about Bangalore traffic in Notepad.", [],
                tools=["write_in_app"])
    journal.add("to thirty percent and play some music", "Set it.", [], tools=["set_volume", "media_play_pause"])
    journal.add("Yes, please do that: Want me to save it?", "Saved.", [], tools=["word_save"])
    r = journal.recap()
    assert r == "Last time, wrote a haiku about Bangalore traffic in Notepad. Before that, I built a snake game in VS Code."
    assert "thirty percent" not in r and "please do that" not in r
    assert "main.py" in journal.context()
    assert journal.files_in(["wrote 111 lines to C:\\a\\b\\main.py; verified"]) == ["C:\\a\\b\\main.py"]

def test_first_greeting_is_a_recap_and_seeds_the_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster import journal
    journal.add("make a snake game in VS Code", "Made a snake game in VS Code.", [], tools=["code_write_file"])
    eng, ex, client, said, fb = make_agent([])
    c, events = _conv(eng, user_name="Andy")
    c.recap = True
    g = c.greeting()
    assert g.startswith("Welcome back, Andy.") and "snake game" in g and "start fresh" in g
    assert eng.in_session() and eng.worker.agent.history[0]["content"] == g
    assert "Andy" in c.greeting() and "Welcome back" not in c.greeting()      # only once


# ---- 0.9.0 ---------------------------------------------------------------------------------
def test_tap_cuts_out_the_monsters_own_voice():
    import numpy as np
    from lazymonster.stt_refine import AudioTap
    clock = Clock()
    tap = AudioTap(clock=clock)
    def add(t, v):
        clock.t = t
        tap.buf.append((t, np.full(1600, v, dtype="float32")))
    add(1.0, 1.0)                                  # you
    clock.t = 1.05; tap.mark_speaking(True)
    add(1.2, 9.0); add(1.5, 9.0)                   # the monster talking
    clock.t = 1.6; tap.mark_speaking(False)
    add(1.8, 9.0)                                  # its echo tail
    add(2.3, 2.0)                                  # you again
    out = tap.slice(0.9, 2.4, preroll=0)
    assert set(np.unique(out)) == {1.0, 2.0}


def test_followup_only_when_it_asked_a_question():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Done."})],
                                            [("finish", {"summary": "Done.", "next": "Want me to save it?"})]])
    eng.followup_only_on_question = True
    eng.on_complete(1, "hey monster make a note please")
    assert "followup" not in fb and eng.armed_until == 0.0
    eng.on_complete(2, "hey monster make another note")
    assert "followup" in fb


@pytest.mark.parametrize("text", ["you can sleep", "go sleep", "just go to sleep man", "thats all", "stop listening"])
def test_sleep_phrases(text):
    exited = []
    eng, ex, *_ = make(on_exit=lambda: exited.append(1))
    eng.on_complete(1, "hey monster " + text)
    assert exited == [1]


def test_agent_can_put_itself_to_sleep():
    slept = []
    eng, ex, client, said, fb = make_agent([[("go_to_sleep", {})]])
    eng.worker.agent.on_sleep = lambda: slept.append(1)
    eng.worker.agent.run("I'm done for today, you can rest")
    assert slept == [1]


def test_json_written_as_text_is_spoken_as_a_sentence():
    eng, ex, client, said, fb = make_agent(['{"summary":"Split the site into pages.","next":"Want shared navigation?"}'])
    eng.worker.agent.run("split the pages")
    assert said == ["Split the site into pages. Want shared navigation?"]
    assert eng.worker.agent.suggestion == "Want shared navigation?"


def test_questions_are_limited_per_task():
    import threading
    eng, ex, client, said, fb = make_agent([[("ask_user", {"question": "A?"})], [("ask_user", {"question": "B?"})],
                                            [("ask_user", {"question": "C?"})], [("finish", {"summary": "ok"})]])
    agent = eng.worker.agent
    agent.ask_timeout = 0.05
    agent.run("do it")
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"]
    assert "Do not ask again" in tool[-1] and said.count("C?") == 0


def test_code_run_approval_is_remembered_per_project():
    import threading
    eng, ex, client, said, fb = make_agent([
        [("code_run", {"project": "snake", "path": "main.py"})], [("code_run", {"project": "snake", "path": "main.py"})],
        [("finish", {"summary": "ok"})]])
    agent = eng.worker.agent
    threading.Timer(0.05, lambda: agent.hear("yes")).start()
    agent.run("run it twice")
    assert said.count("Run main.py from snake now?") == 1 and [c.name for c in ex.calls] == ["code_run", "code_run"]


def test_escalates_to_stronger_model_after_failures():
    class Failing(DryRunExecutor):
        def run(self, intent):
            self.calls.append(intent); return False, "nope", None
    eng, ex, client, said, fb = make_agent([[("list_windows", {})], [("list_windows", {})]])
    strong = ScriptedClient([[("finish", {"summary": "Fixed it."})]])
    strong.model = "gpt-6-astra"
    agent = eng.worker.agent
    agent.ex, agent.escalation = Failing(), strong
    agent.run("hard thing")
    assert said[-1].startswith("Fixed it.")


def test_web_research_reads_sources():
    from lazymonster.agent import _responses_text
    data = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": "output_text", "text": "Meta released Llama 5.", "annotations": [
            {"type": "url_citation", "url": "https://ai.meta.com/x", "title": "Meta AI"}]}]}]}
    text, src = _responses_text(data)
    assert text == "Meta released Llama 5." and src == [("Meta AI", "https://ai.meta.com/x")]


def test_outline_builds_a_real_deck(tmp_path):
    from pptx import Presentation
    from lazymonster.office_docs import build_pptx, parse_outline
    outline = "# Meta AI\nWhat it is and why it matters\n# What is Meta AI\n- Assistant in WhatsApp\n- Llama models\n# Why it matters\n- Billions of users"
    assert [s[0] for s in parse_outline(outline)] == ["Meta AI", "What is Meta AI", "Why it matters"]
    p = build_pptx("Meta AI", outline, tmp_path / "deck.pptx")
    assert len(Presentation(str(p)).slides) == 3


def test_open_file_only_documents_in_your_folders(tmp_path, monkeypatch):
    from lazymonster.actions import files
    monkeypatch.setattr(files, "out_dir", lambda: tmp_path)
    monkeypatch.setattr(files.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "code" / "cafe").mkdir(parents=True)
    (tmp_path / "code" / "cafe" / "index.html").write_text("<h1>cafe</h1>")
    (tmp_path / "code" / "cafe" / "run.bat").write_text("echo hi")
    assert files.resolve_file("cafe/index.html").name == "index.html"
    assert files.resolve_file("index.html").name == "index.html"
    with pytest.raises(GuardError):
        files.resolve_file("cafe/run.bat")
    with pytest.raises(GuardError):
        files.resolve_file("C:/Windows/System32/notepad.exe")


# ---- 0.10.0: voice lock, push-to-talk, orb ------------------------------------------------
def test_voice_lock_blocks_other_voices():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.verify = lambda t0: False                          # not Andy
    eng.on_complete(1, "hey monster mute")
    eng.on_complete(2, "hey monster open notepad and write a poem")
    assert ex.calls == [] and client.seen == [] and fb.count("unknown") == 2


def test_voice_lock_lets_you_through():
    eng, ex, *_ = make_agent([])
    eng.verify = lambda t0: True
    eng.on_complete(1, "hey monster mute")
    assert ex.calls == [Intent.make("mute")]


def test_typed_and_push_to_talk_skip_the_lock():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.verify = lambda t0: False
    eng.handle_text("mute")                               # typed
    assert ex.calls == [Intent.make("mute")]
    c, events = _conv(eng)
    eng.feedback = c.feedback
    c.push_to_talk()                                       # hotkey / click on the orb
    eng.on_complete(9, "unmute")
    assert ex.calls[-1] == Intent.make("unmute")


def test_voice_lock_errors_never_lock_you_out():
    eng, ex, *_ = make_agent([])
    def boom(t0): raise RuntimeError("model missing")
    eng.verify = boom
    eng.on_complete(1, "hey monster mute")
    assert ex.calls == [Intent.make("mute")]


@pytest.mark.parametrize("combo,ok", [("ctrl+alt+space", True), ("win+shift+m", True), ("space", False), ("ctrl+nope", False)])
def test_hotkey_parse(combo, ok):
    from lazymonster.hotkey import parse
    if ok:
        mods, vk = parse(combo)
        assert mods & 0x4000 and vk
    else:
        with pytest.raises(ValueError):
            parse(combo)


def test_sleep_goes_to_orb_not_quit():
    from lazymonster.ui.app import UIBus
    bus = UIBus()
    sent = []
    bus._send = sent.append
    bus.ready.set()
    class W:
        calls = []
        def resize(self, w, h): W.calls.append(("resize", w, h))
        def move(self, x, y): W.calls.append(("move", x, y))
        def show(self): W.calls.append(("show",))
    bus.window, bus.geom = W(), {"full": (10, 20, 400, 760), "orb": (900, 700, 170, 180)}
    bus.set_orb(True)
    bus.set_orb(False)
    assert [e for e in sent if e["type"] == "orb"] == [{"type": "orb", "on": True}, {"type": "orb", "on": False}]
    assert ("resize", 170, 180) in W.calls and ("resize", 400, 760) in W.calls


# ---- 0.11.0: macOS ------------------------------------------------------------------------
@pytest.mark.parametrize("combo,expect", [("cmd+shift+space", "<cmd>+<shift>+<space>"), ("ctrl+alt+m", "<ctrl>+<alt>+m"),
                                          ("option+f5", "<alt>+<f5>")])
def test_mac_hotkey_format(combo, expect):
    from lazymonster.hotkey import to_pynput
    assert to_pynput(combo) == expect


def test_refiner_per_machine(monkeypatch):
    from lazymonster import platform_info, stt_refine
    from lazymonster.config import Config
    cfg = Config()
    for arm, mac, cls in [(True, True, "MLXRefiner"), (False, True, "FasterWhisperRefiner"), (False, False, "WhisperRefiner")]:
        monkeypatch.setattr(platform_info, "IS_APPLE_SILICON", arm)
        monkeypatch.setattr(platform_info, "IS_MAC", mac)
        assert type(stt_refine.make_refiner(cfg, [])).__name__ == cls


def test_keychain_used_on_mac(monkeypatch):
    from lazymonster import secrets
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "IS_MAC", True)
    class R: returncode, stdout = 0, "sk-from-keychain\n"
    calls = []
    monkeypatch.setattr(secrets.subprocess, "run", lambda *a, **k: calls.append(a[0]) or R())
    assert secrets.get_key("OPENAI_API_KEY") == "sk-from-keychain"
    assert calls[0][:3] == ["security", "find-generic-password", "-s"]


class _FakeRec:
    """Stands in for the sherpa recognizer: 'hears' the blocks it gets as text."""
    def __init__(self): self.fed = []
    def create_stream(self): return _FakeStream(self)
    def is_ready(self, s): return False
    def decode_stream(self, s): pass
    def get_result(self, s): return ""
    def is_endpoint(self, s): return False
    def reset(self, s): pass


class _FakeStream:
    def __init__(self, rec): self.rec = rec
    def accept_waveform(self, sr, block): self.rec.fed.append(float(block.max()) if len(block) else 0.0)


def test_sherpa_mic_modes(monkeypatch):
    import numpy as np
    from lazymonster import stt_sherpa
    monkeypatch.setattr(stt_sherpa, "recognizer", lambda pause_s=0.6: _FakeRec())
    m = stt_sherpa.SherpaMic(lambda l, t: None, lambda l, t: None)
    rec = m.rec
    m.set_reasons({"idle"})                                   # asleep: nothing decoded, but remembered
    for v in (1.0, 2.0):
        m.on_audio(np.full(1600, v, dtype=np.float32))
    m.drain()
    before = len(rec.fed)
    m.set_reasons(set())                                      # wake: warm-up silence, then the replay
    m.drain()
    assert rec.fed[before:] == [0.0, 1.0, 2.0]
    m.set_reasons({"speaking"})                               # its own voice: fed as silence
    m.on_audio(np.full(1600, 9.0, dtype=np.float32)); m.drain()
    assert rec.fed[-1] == 0.0


def test_mac_launch_agent(tmp_path, monkeypatch):
    import plistlib
    from lazymonster import service
    monkeypatch.setattr(service.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
    p = service._install_mac()
    d = plistlib.loads(open(p, "rb").read())
    assert d["Label"] == "com.lazymonster.agent" and d["RunAtLoad"] is True and "--background" in d["ProgramArguments"]


# ---- 1.0.1: brains, voice lock feedback -----------------------------------------------------
def test_claude_client_converts_both_ways():
    from lazymonster.agent import ClaudeClient
    msgs = [{"role": "system", "content": "You are the monster."},
            {"role": "user", "content": "open notepad"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
             "function": {"name": "open_app", "arguments": '{"app": "notepad"}'}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "opened notepad"},
            {"role": "system", "content": "You have used your step budget."}]
    tools = [{"type": "function", "function": {"name": "open_app", "description": "Open an app",
              "parameters": {"type": "object", "properties": {"app": {"type": "string"}}}}}]
    body = ClaudeClient.to_anthropic(msgs, tools)
    assert body["system"] == "You are the monster."
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"]                      # strict turn-taking
    assert body["messages"][1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "open_app", "input": {"app": "notepad"}}
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["messages"][2]["content"][1]["text"].startswith("[note]")
    assert body["tools"][0]["input_schema"]["properties"]["app"]["type"] == "string"
    out = ClaudeClient.to_openai({"content": [{"type": "text", "text": "Opening it."},
                                              {"type": "tool_use", "id": "t2", "name": "finish", "input": {"summary": "done"}}]})
    m = out["choices"][0]["message"]
    assert m["content"] == "Opening it." and m["tool_calls"][0]["function"]["name"] == "finish"
    assert json.loads(m["tool_calls"][0]["function"]["arguments"]) == {"summary": "done"}


def test_build_client_per_provider(monkeypatch):
    from lazymonster.agent import AgentError, ChatClient, ClaudeClient, build_client
    from lazymonster.config import Config
    monkeypatch.setenv("OPENAI_API_KEY", "k1"); monkeypatch.setenv("ANTHROPIC_API_KEY", "k2"); monkeypatch.setenv("JEV_API_KEY", "k3")
    cfg = Config()
    cfg.planner = "openai"; assert type(build_client(cfg)) is ChatClient
    cfg.planner = "anthropic"; c = build_client(cfg); assert type(c) is ClaudeClient and c.model == cfg.anthropic_model
    assert build_client(cfg, escalation=True) is None                  # "go big" is opt-in
    cfg.go_big = True
    assert build_client(cfg, escalation=True).model == cfg.anthropic_escalation_model
    cfg.planner = "jev"
    with pytest.raises(AgentError):
        build_client(cfg)                                             # Jev decides; it doesn't write
    cfg.planner = "none"; assert build_client(cfg) is None


def test_voice_lock_rejection_is_explained_once_per_wake():
    eng, ex, client, said, fb = make_agent([])
    c, events = _conv(eng)
    eng.feedback, eng.log = c.feedback, lambda **ev: c.log(ev)
    eng.verify = lambda t0: (False, 0.31)
    eng.wake_up()
    eng.on_complete(1, "open notepad and write a poem")
    eng.on_complete(2, "open notepad and write a poem")
    hints = [e for e in events if e.get("type") == "say" and "didn't sound like you" in e["text"]]
    assert len(hints) == 1


def test_tui_meter_and_dots():
    from lazymonster import tui
    assert tui.dots(2, 4).count("\u25cf") == 2 and tui.dots(2, 4).count("\u25cb") == 2
    assert "\u2588" in tui.meter(0.1)


def test_local_whisper_folder_is_used(tmp_path):
    from lazymonster.stt_refine import WhisperRefiner
    r = WhisperRefiner(str(tmp_path))
    assert r.path == tmp_path


# ---- 1.0.2: Jev as a decider (TypeSafe System One) ----------------------------------------------
class FakeJev:
    def __init__(self, addressed=0.9, agreed=0.9, plan=None):
        self._a, self._g, self._p, self.calls = addressed, agreed, plan, []
    def addressed(self, heard, last_said=""):
        self.calls.append(("addressed", heard)); return self._a
    def agreed(self, q, a):
        self.calls.append(("agreed", a)); return self._g
    def plan(self, task, tools):
        self.calls.append(("plan", task)); return self._p


def test_jev_ignores_room_chatter_in_the_followup_window():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Done.", "next": "Want me to save it?"})]])
    eng.jev = FakeJev(addressed=0.1)
    eng.on_complete(1, "hey monster write a note please")
    before = len(client.seen)
    eng.on_complete(2, "no mum I said I'll be down in five minutes")      # follow-up window, no wake word
    assert len(client.seen) == before and ("addressed", "no mum I said I'll be down in five minutes") in eng.jev.calls


def test_jev_not_asked_after_a_wake_word():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "ok"})]])
    eng.jev = FakeJev(addressed=0.0)
    eng.on_complete(1, "hey monster write a note please")
    assert not [c for c in eng.jev.calls if c[0] == "addressed"] and client.seen


def test_jev_plan_feeds_tree_and_starts_hard_tasks_on_the_stronger_model():
    eng, ex, client, said, fb = make_agent([])
    strong = ScriptedClient([[("finish", {"summary": "Built it."})]]); strong.model = "claude-sonnet-5"
    agent = eng.worker.agent
    agent.escalation = strong
    agent.jev = FakeJev(plan={"candidates": [{"tool": "code_write_file", "p": 0.7}], "difficulty": 1.8})
    logs = []
    agent.log = lambda **k: logs.append(k)
    agent.run("build me a full snake game with levels")
    assert said[-1].startswith("Built it.") and client.seen == []
    assert any(l.get("event") == "agent_think" and l.get("source") == "jev" for l in logs)


def test_jev_understands_informal_yes():
    import threading
    eng, ex, client, said, fb = make_agent([[("code_run", {"project": "snake", "path": "main.py"})],
                                            [("finish", {"summary": "ok"})]])
    agent = eng.worker.agent
    agent.jev = FakeJev(agreed=0.93)
    threading.Timer(0.05, lambda: agent.hear("why not, go for it")).start()
    agent.run("run the game")
    assert ex.calls and ex.calls[-1].name == "code_run"


def test_jev_http_shape(monkeypatch):
    from lazymonster import jev
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    sent = {}
    class R:
        status_code = 200
        def json(self): return {"answers": {"addressed": {"type": "noul", "noul": 0.12}}}
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.update(url=url, **k) or R())
    j = jev.Jev()
    assert j.addressed("pass the salt", "Want me to save it?") == 0.12
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone" and sent["json"]["model"] == "jev-latest"
    assert sent["headers"]["Authorization"] == "Bearer ts-key" and sent["json"]["questions"]["addressed"]["type"] == "noul"


def test_jev_down_means_business_as_usual(monkeypatch):
    from lazymonster import jev
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    import requests
    def boom(*a, **k): raise requests.exceptions.ConnectTimeout()
    monkeypatch.setattr(requests, "post", boom)
    assert jev.Jev().addressed("hello") is None


def test_voice_lock_helper_fails_open():
    import numpy as np
    from lazymonster.voicelock import VoiceLockProcess
    v = VoiceLockProcess.__new__(VoiceLockProcess)
    class Dead:
        def poll(self): return 1
    import threading
    v.p, v.timeout, v._lock = Dead(), 0.1, threading.Lock()
    assert v.check(np.ones(16000, dtype=np.float32)) == (True, -1.0)


def test_false_wake_stays_silent_and_real_wake_works():
    import time as _t
    from lazymonster import conversation as C
    eng, *_ = make()
    c, events = _conv(eng)
    eng.feedback = c.feedback
    logs = []
    eng.log = lambda **k: logs.append(k)
    c.confirm_wake = lambda: (False, "whisper heard 'thank you'")
    c.on_wake(0.97); _t.sleep(0.05)
    assert c.state == C.SLEEPING and logs[-1]["event"] == "wake_rejected"
    c.confirm_wake = lambda: (True, "hey monster")
    c.on_wake(0.97); _t.sleep(0.05)
    assert c.state == C.LISTENING


def test_greeting_only_every_so_often():
    from lazymonster import conversation as C
    eng, *_ = make()
    c, events = _conv(eng, user_name="Andy")
    eng.feedback = c.feedback
    for _ in range(3):
        c.set(C.SLEEPING); eng.wake_up(); eng.clock.t += 1; c._maybe_greet()
    assert len(c.speaker.said) == 1


def test_running_counts_one_monster_per_launcher_chain(monkeypatch):
    from lazymonster import service
    class P:
        def __init__(self, pid, ppid): self.pid, self.info = pid, {"ppid": ppid}
    chain = [P(10, 1), P(11, 10), P(12, 11)]
    monkeypatch.setattr(service, "_matches", lambda: chain)
    assert [p.pid for p in service.running()] == [10]


# ---- 1.1.0: local brains, web research without a cloud, window and status ---------------------
def test_parse_duckduckgo_results():
    from lazymonster.websearch import parse_ddg
    page = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fai.meta.com%2Fblog%2F&amp;rut=x">'
            'Meta <b>AI</b> blog</a><a class="result__a" href="https://example.org/news">Example news</a>')
    assert parse_ddg(page) == [("Meta AI blog", "https://ai.meta.com/blog/"), ("Example news", "https://example.org/news")]


def test_page_text_skips_scripts_and_nav():
    from lazymonster.websearch import page_text
    assert page_text("<nav>Menu</nav><script>x=1</script><p>Llama 5 was released in <b>May</b>.</p>") == "Llama 5 was released in May ."


def test_local_research_uses_search_and_cites(monkeypatch):
    from lazymonster import websearch
    monkeypatch.setattr(websearch, "search", lambda q, limit=6: [("A", "https://a.example"), ("B", "https://b.example")])
    monkeypatch.setattr(websearch, "fetch", lambda url, limit=3000: "Fact about " + url + ". " * 120)
    class Brain:
        def chat(self, messages, tools=None):
            assert "[1]" in messages[1]["content"] and "[2]" in messages[1]["content"]
            return {"choices": [{"message": {"content": "Answer [1]."}}]}
    out = websearch.research(Brain(), "what happened?")
    assert out.startswith("Answer [1].") and "https://a.example" in out


def test_local_brain_needs_no_key_and_goes_big_to_the_cloud(monkeypatch):
    from lazymonster.agent import ChatClient, LocalClient, build_client
    from lazymonster.config import Config
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config(); cfg.planner, cfg.local_base_url, cfg.local_model = "local", "http://localhost:11434/v1", "qwen3:8b"
    c = build_client(cfg)
    assert type(c) is LocalClient and c.model == "qwen3:8b" and hasattr(c, "research")
    cfg.go_big = True
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    big = build_client(cfg, escalation=True)
    assert type(big) is ChatClient and big.model == cfg.escalation_model
    monkeypatch.delenv("OPENAI_API_KEY")
    assert build_client(cfg, escalation=True) is None


def test_window_starts_bottom_left_and_keeps_your_spot():
    from lazymonster.ui.app import corner_geom
    g = corner_geom(1920, 1080)
    assert g["full"][0] == 16 and g["full"][1] == 1080 - 760 - 56 and g["orb"][0] == 16
    g = corner_geom(1920, 1080, saved=(1400, 200))
    assert g["full"][:2] == (1400, 200) and g["orb"][0] > 1000              # orb follows to the right side
    assert corner_geom(1920, 1080, saved=(5000, 200))["full"][0] == 16      # off-screen spot is ignored


def test_status_event_shape():
    from lazymonster.cli import status_event
    from lazymonster.config import Config
    cfg = Config(); cfg.planner, cfg.go_big = "anthropic", True
    ev = status_event(cfg, True, {"wake": "wake word on NPU", "stt": "Whisper on GPU", "lock": "voice lock on"}, "Kokoro")
    assert ev["wake_dev"] == "NPU" and ev["brain"].startswith("Claude") and ev["big"] and ev["lock"]
    assert status_event(cfg, False, {}, "Kokoro")["brain"] == ""


def test_voice_move_command():
    moved = []
    eng, ex, *_ = make()
    eng.on_move = moved.append
    eng.on_complete(1, "hey monster move to the right")
    assert moved == ["right"] and ex.calls == []


# ---- 1.2.0: live brain, settings, conversation ----------------------------------------------------
def test_turn_waits_longer_after_a_dangling_word():
    eng, *_ = make()
    eng.turn_delay = 0.9
    assert eng.turn_delay_for("open the") == 1.8
    assert eng.turn_delay_for("what time is it?") < 0.9
    assert eng.turn_delay_for("write a haiku about rain") == 0.9


def test_conversation_mode_keeps_listening_without_a_question():
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Done."})]])
    eng.followup_only_on_question, eng.conversation_mode = True, True
    eng.on_complete(1, "hey monster make a note please")
    assert "followup" in fb


def _brain_rig(monkeypatch, tmp_path):
    from lazymonster.agent import Agent
    from lazymonster.config import Config
    from lazymonster.control import BrainControl
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    eng, ex, *_ = make_agent([])
    cfg = Config()
    ctl = BrainControl(cfg, eng, lambda c: Agent(c, ex, lambda **k: None, lambda t: None))
    ctl.validate = lambda client: None
    return eng, cfg, ctl


def test_switch_brain_live(monkeypatch, tmp_path):
    from lazymonster.agent import ClaudeClient
    eng, cfg, ctl = _brain_rig(monkeypatch, tmp_path)
    assert "need a Claude key" in ctl.switch("claude") and cfg.planner == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
    msg = ctl.switch("claude")
    assert cfg.planner == "anthropic" and type(eng.worker.agent.client) is ClaudeClient and "Claude" in msg


def test_go_big_by_voice(monkeypatch, tmp_path):
    eng, cfg, ctl = _brain_rig(monkeypatch, tmp_path)
    eng.on_brain = ctl.handle
    spoken = []
    eng.say = spoken.append
    eng.on_complete(1, "hey monster use the bigger brain")
    assert cfg.go_big and eng.worker.agent.escalation.model == cfg.escalation_model and "gpt-6-astra" in spoken[-1]
    eng.on_complete(2, "hey monster which brain are you using")
    assert spoken[-1].startswith("I'm using OpenAI")


def test_settings_apply_live(monkeypatch, tmp_path):
    from lazymonster.settings_ctl import SettingsCtl
    eng, cfg, ctl = _brain_rig(monkeypatch, tmp_path)
    eng.brain = ctl
    c, events = _conv(eng)
    class Det:
        class head: threshold = 0.95
        threshold = 0.95
    det = Det()
    s = SettingsCtl(cfg, eng, c, c.speaker, None, {"detector": det}, {"lock": None, "verify": None}, lambda: None)
    s.set("wake_sensitivity", 0.1)
    assert abs(det.threshold - 0.85) < 1e-9
    s.set("conversation_mode", False)
    assert eng.conversation_mode is False and eng.followup_window == 10.0
    assert "Enroll" in s.set("voice_lock", True)
    got = s.get()
    assert got["planner"] == "openai" and got["have"]["openai"] and got["voices"]


def test_barge_in_by_loudness_with_tv_veto():
    import numpy as np
    import time as _t
    from lazymonster import conversation as C
    eng, *_ = make()
    c, events = _conv(eng)
    eng.feedback = c.feedback
    class Tap:
        def raw(self, s): return np.ones(16000, dtype=np.float32) * 0.1
    class Lock:
        threshold = 0.7
        def __init__(self, s): self.s = s
        def check(self, a): return (self.s >= 0.7, self.s)
    c.tap = Tap()
    for lock, expect in ((None, 1), (Lock(0.2), 0), (Lock(0.55), 1)):    # no lock / a TV / you, over the echo
        c.lock = lock
        c.set(C.SPEAKING); c.spoke_at = eng.clock.t - 5
        c.speaker.stopped = 0
        for _ in range(12):
            c.on_audio(np.ones(800, dtype=np.float32) * 0.1)
        _t.sleep(0.1)
        assert c.speaker.stopped == expect, (lock, c.speaker.stopped)


def test_echo_alone_does_not_interrupt():
    import numpy as np
    from lazymonster import conversation as C
    eng, *_ = make()
    c, events = _conv(eng)
    class K:
        playing = (np.ones(24000 * 10, dtype=np.float32) * 0.2, 24000, __import__("time").monotonic() - 1)
    c.speaker.kokoro = K()
    c.set(C.SPEAKING); c.spoke_at = eng.clock.t - 5
    c.speaker.stopped = 0
    for _ in range(40):                       # the mic hears the monster at a steady ratio (its echo)
        c.on_audio(np.ones(800, dtype=np.float32) * 0.06)
    assert c.speaker.stopped == 0

def test_version_compare():
    from lazymonster.cli import _newer
    assert _newer("1.2.1", "1.2.0") and not _newer("1.2.0", "1.2.0") and _newer("1.10.0", "1.9.9")


def test_bad_model_is_rejected_and_the_working_one_kept(monkeypatch, tmp_path):
    from lazymonster.agent import AgentError
    eng, cfg, ctl = _brain_rig(monkeypatch, tmp_path)
    ctl.reload()
    def picky(client):
        if client.model == "gpt-5.4-pro":
            raise AgentError("HTTP 404: this model is only in the Responses API")
    ctl.validate = picky
    msg = ctl.set_model("gpt-5.4-pro")
    assert "didn't work" in msg and cfg.openai_model == "gpt-5.4-mini" and eng.worker.agent.client.model == "gpt-5.4-mini"
    assert ctl.set_model("gpt-5.4") == "Now using gpt-5.4." and eng.worker.agent.client.model == "gpt-5.4"


# ---- 1.3.0: reminders that come to you, voice lock accuracy -----------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("at 8 AM", "2026-09-25 08:00"), ("at 8", "2026-09-25 08:00"), ("at 8:30 pm", "2026-09-25 20:30"),
    ("in 10 minutes", "2026-09-24 22:25"), ("in half an hour", "2026-09-24 22:45"), ("tomorrow morning", "2026-09-25 08:00"),
    ("tonight at 11", "2026-09-24 23:00"), ("at noon", "2026-09-25 12:00")])
def test_reminder_times(text, expect):
    from datetime import datetime
    from lazymonster.reminders import parse_when
    assert parse_when(text, datetime(2026, 9, 24, 22, 15)).strftime("%Y-%m-%d %H:%M") == expect


def test_reminder_by_voice_list_cancel(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    eng, ex, *_ = make()
    spoken = []
    eng.say = spoken.append
    eng.on_complete(1, "hey monster remind me about the cafe website meeting at 8 AM")
    assert "cafe website meeting" in spoken[-1] and "8 AM" in spoken[-1] and ex.calls == []
    eng.on_complete(2, "hey monster what are my reminders")
    assert "cafe website meeting" in spoken[-1]
    eng.on_complete(3, "hey monster cancel the cafe reminder")
    assert spoken[-1].startswith("Cancelled")


def test_due_reminder_fires_once_and_late_ones_within_3h(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster import reminders
    reminders.add("the cafe website meeting", "at 8 AM", now=datetime(2026, 9, 24, 7, 0))
    reminders.add("old thing", "at 1 AM", now=datetime(2026, 9, 24, 0, 30))
    fired = []
    s = reminders.Scheduler(lambda r, late: fired.append((r["what"], late)), clock=lambda: datetime(2026, 9, 24, 8, 0, 30))
    s.tick(); s.tick()
    assert fired == [("the cafe website meeting", False)]           # 1 AM is 7 h late: dropped, not nagged


def test_reminder_suggests_and_waits_for_your_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    eng, ex, client, said, fb = make_agent([[("draft_email", {"subject": "Cafe website meeting", "body": "Agenda..."})],
                                            [("finish", {"summary": "The draft is open for you to review."})]])
    agent = eng.worker.agent
    agent.suggest = lambda about: ["open the cafe website project", "update the menu page", "draft an agenda email"]
    c, events = _conv(eng, user_name="Andy")
    eng.feedback = c.feedback
    c.nudge_after = 3600
    c.remind({"id": "r1", "what": "the cafe website meeting", "when": "2026-09-24T08:00"})
    line = c.speaker.said[-1]
    assert line.startswith("Andy, it's 8 AM. Reminder: the cafe website meeting.") and "draft an agenda email" in line
    assert ex.calls == []                                           # nothing done before you pick
    eng.on_complete(7, "the last one")                              # no wake word: it's waiting for you
    assert [x.name for x in ex.calls] == ["draft_email"]
    hist = [m["content"] for m in client.seen if m.get("role") == "assistant" and m.get("content")]
    assert any("Options I offered" in h for h in hist)


def test_voice_lock_is_fair_to_short_commands():
    import numpy as np
    from lazymonster.voicelock import VoiceLock
    v = VoiceLock.__new__(VoiceLock)
    v.threshold = 0.68
    assert abs(v.threshold_for(0.6) - 0.53) < 1e-9 and v.threshold_for(2.5) == 0.68
    x = np.concatenate([np.zeros(16000), np.sin(np.arange(16000) / 5) * 0.2, np.zeros(16000)]).astype(np.float32)
    sp = VoiceLock.speech(x)
    assert 16000 <= len(sp) <= 16000 + 320 * 12


def test_kokoro_speaks_without_falling_back(monkeypatch):
    import sys, types
    import numpy as np
    from lazymonster.tts import KokoroVoice, Speaker
    played = []
    class Stream:
        active = False
    fake_sd = types.SimpleNamespace(play=lambda a, samplerate: played.append(len(a)), get_stream=lambda: Stream(),
                                    stop=lambda: None)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    k = KokoroVoice()
    k.k = types.SimpleNamespace(create=lambda s, voice, speed, lang: (np.zeros(2400, np.float32), 24000))
    s = Speaker("kokoro")
    s.kokoro = k
    fell_back = []
    s.on_fallback = fell_back.append
    s._windows = lambda text: fell_back.append("windows")
    s.say("Hello there. This is the monster.")
    assert played and fell_back == []


def test_local_model_thinking_is_not_spoken(monkeypatch):
    from lazymonster.agent import ChatClient, LocalClient
    monkeypatch.setattr(ChatClient, "chat", lambda self, m, t=None: {"choices": [{"message": {
        "role": "assistant", "content": "<think>The user wants notepad. I should call open_app.</think>\nOpening it."}}]})
    c = LocalClient("http://localhost:11434/v1", "qwen3.5:9b")
    assert c.chat([])["choices"][0]["message"]["content"] == "Opening it."


# ---- 1.4.0: awake while working, sees the PC and the screen ------------------------------------------
def test_never_falls_asleep_during_a_task():
    from lazymonster import conversation as C
    eng, *_ = make_agent([])
    c, events = _conv(eng)
    c.log({"event": "task", "text": "build the cafe page"})
    eng.worker.busy.set()
    eng.armed_until = 0.0
    c._before = C.THINKING
    assert c._resume() == C.THINKING                   # "On it" finished: stay awake, not asleep
    c.set(C.THINKING); c.tick()
    assert c.state == C.THINKING
    c.log({"event": "agent_done"}); eng.worker.busy.clear()
    assert not c.task_active


def test_system_status_through_the_agent(monkeypatch):
    from lazymonster import sysinfo
    monkeypatch.setattr(sysinfo, "snapshot", lambda top=6: {"cpu_percent": 12.0, "cpu_cores": 22, "ram_used_gb": 29.5,
        "ram_total_gb": 31.4, "ram_percent": 94, "disk_free_gb": 200, "disk_percent": 60, "battery": None,
        "gpu": {"gpu3d": 8, "compute": 0, "shared_gb": 20.9},
        "top_cpu": [], "top_ram": [{"name": "llama-server", "gb": 4.0}], "at": "10:00"})
    eng, ex, client, said, fb = make_agent([[("system_status", {})], [("finish", {"summary": "llama-server is holding the memory."})]])
    eng.worker.agent.run("why is my laptop slow")
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"][0]
    assert "94%" in tool and "20.9 GB" in tool and "local AI model server" in tool


def test_look_at_screen_answers_and_refuses_private_windows():
    eng, ex, client, said, fb = make_agent([[("look_at_screen", {"question": "explain this error"})],
                                            [("finish", {"summary": "ok"})]])
    seen = {}
    client.vision = lambda q, shot: seen.update(q=q, shot=shot) or "A None value is being indexed."
    client.model = "x"; client.base_url = "http://x"
    eng.worker.agent.run("explain this error")
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"][0]
    assert tool == "A None value is being indexed." and "NoneType" in seen["shot"]["text"]
    ex.screen = {"blocked": True, "title": "[private window]"}
    client.turns = [[("look_at_screen", {"question": "what's this"})], [("finish", {"summary": "ok"})]]
    eng.worker.agent.run("what's on my screen")
    tool = [m["content"] for m in client.seen if m.get("role") == "tool"][-1]
    assert "private" in tool


def test_model_check_gives_up_after_30s_with_a_reason():
    import requests
    from lazymonster.agent import AgentError
    from lazymonster.control import can_drive_apps
    class Slow:
        timeout = 180.0
        def chat(self, m, t=None):
            assert self.timeout == 30.0
            raise requests.exceptions.ReadTimeout("Read timed out.")
    c = Slow()
    with pytest.raises(AgentError) as e:
        can_drive_apps(c)
    assert "still be loading" in str(e.value) and c.timeout == 180.0


def test_cpu_question_without_a_brain_gets_a_spoken_answer(monkeypatch):
    from lazymonster import sysinfo
    monkeypatch.setattr(sysinfo, "snapshot", lambda top=6: {"cpu_percent": 12.0, "ram_percent": 94,
                                                            "top_ram": [{"name": "llama-server", "gb": 4.0}]})
    eng, ex, *_ = make()
    spoken = []
    eng.say = spoken.append
    eng.on_complete(1, "hey monster check my cpu usage")
    assert spoken == ["CPU is at 12 percent and memory at 94 percent. llama-server uses the most memory. Memory is nearly full."]


# ---- 1.5.0: looks, pet, on-device screen reading --------------------------------------------------
def test_seasonal_outfits():
    import datetime as dt
    from lazymonster.looks import seasonal
    assert seasonal(dt.date(2026, 11, 8)) == "diwali" and seasonal(dt.date(2026, 12, 24)) == "santa"
    assert seasonal(dt.date(2027, 4, 10)) == "cricket" and seasonal(dt.date(2026, 9, 24)) == ""


def _look_rig(monkeypatch, brain_type="ChatClient", allow=False):
    from lazymonster.config import Config
    eng, ex, client, said, fb = make_agent([[("look_at_screen", {"question": "what does it say"})],
                                            [("finish", {"summary": "ok"})]])
    agent = eng.worker.agent
    agent.cfg = Config(); agent.cfg.send_screenshots = allow
    ex.screen = {"title": "Remote Desktop", "app": "mstsc.exe", "text": "", "image": "aGVsbG8="}
    monkeypatch.setattr(type(agent), "_ocr", staticmethod(lambda img, dev="auto": "TypeError on line 42"))
    seen = {}
    Brain = type(brain_type, (), {"vision": lambda self, q, shot: seen.update(shot=dict(shot)) or "It's a TypeError."})
    agent.client = client
    client.vision = Brain().vision
    client.__class__ = type(brain_type, (type(client),), {})
    agent.run("what does my screen say")
    return seen["shot"]


def test_screen_text_is_read_on_device_and_images_stay_home(monkeypatch):
    shot = _look_rig(monkeypatch)
    assert "TypeError on line 42" in shot["text"] and shot["image"] is None       # cloud brain: text only
    shot = _look_rig(monkeypatch, allow=True)
    assert shot["image"] == "aGVsbG8="                                          # you allowed screenshots
    shot = _look_rig(monkeypatch, brain_type="LocalClient")
    assert shot["image"] == "aGVsbG8="                                          # a local brain keeps it on the PC


def test_skin_and_outfit_apply_live(monkeypatch, tmp_path):
    from lazymonster.settings_ctl import SettingsCtl
    eng, cfg, ctl = _brain_rig(monkeypatch, tmp_path)
    eng.brain = ctl
    c, events = _conv(eng)
    sent = []
    bus = type("B", (), {"emit": lambda self, e: sent.append(e)})()
    s = SettingsCtl(cfg, eng, c, c.speaker, bus, {}, {"lock": None, "verify": None}, lambda: None)
    s.set("skin", "mint"); s.set("outfit", "party")
    assert sent[-1] == {"type": "skin", "skin": "mint", "outfit": "party"} and s.get()["skin"] == "mint"


def test_watchdog_restarts_after_a_crash_and_stops_when_you_quit(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster import watchdog, service
    monkeypatch.setattr(service, "single_instance", lambda kind="background": True)
    codes, envs = [3221225477, 0], []
    monkeypatch.setattr(watchdog.subprocess, "call", lambda cmd, env, creationflags: envs.append(env) or codes.pop(0))
    monkeypatch.setattr(watchdog.time, "sleep", lambda s: None)
    assert watchdog.supervise(["ui", "--background"]) == 0
    assert len(envs) == 2 and "LM_RESTARTED" in envs[1] and envs[1]["LM_SUPERVISED"] == "1"
    report = open(envs[1]["LM_RESTARTED"]).read()
    assert "0xc0000005" in report


def test_watchdog_gives_up_after_repeated_crashes(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from lazymonster import watchdog, service
    monkeypatch.setattr(service, "single_instance", lambda kind="background": True)
    calls = []
    monkeypatch.setattr(watchdog.subprocess, "call", lambda cmd, env, creationflags: calls.append(1) or 1)
    monkeypatch.setattr(watchdog.time, "sleep", lambda s: None)
    assert watchdog.supervise(["ui", "--background"]) == 1 and len(calls) == watchdog.MAX_RESTARTS + 1


# ---- 1.6.0: the quick brain on the NPU -----------------------------------------------------------
def test_quick_brain_parses_its_json():
    from lazymonster.npu_brain import parse
    assert parse('{"tool": "open_app", "args": {"app": "Spotify"}, "say": "Opening."}')["tool"] == "open_app"
    assert parse("Sure! {'tool': 'mute', 'args': {}}")["tool"] == "mute"
    assert parse("I think you should open notepad")["tool"] == "hand_off"


def test_quick_brain_does_simple_things_and_hands_off_the_rest():
    from lazymonster.config import Config
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Built the game."})]])
    agent = eng.worker.agent
    agent.cfg = Config(); agent.cfg.quick_brain = True
    from lazymonster.intents import validate
    class Q:
        def handle(self, task):
            if "spotify" in task:
                return validate("open_app", {"app": "Spotify"}, source="agent"), "Opening Spotify.", 0.4
            raise AssertionError("big requests must not reach the quick brain")
            return None
    agent.quick = Q()
    agent.run("open spotify please")
    assert [c.name for c in ex.calls] == ["open_app"] and said[-1] == "Opening Spotify." and client.seen == []
    agent.run("build a snake game")
    assert client.seen and said[-1].startswith("Built the game.")          # handed to the main brain


def test_quick_brain_only_sees_simple_requests():
    from lazymonster.npu_brain import SYSTEM, looks_simple
    assert looks_simple("open spotify") and looks_simple("remind me in 20 minutes to stretch")
    assert not looks_simple("research the latest nvidia news and make three slides")
    assert not looks_simple("build a snake game in python") and not looks_simple("email Priya the menu")
    assert len(SYSTEM.split()) < 300


def test_quick_brain_near_misses_map_to_real_tools():
    from lazymonster.npu_brain import normalize, parse
    assert normalize(parse('{"tool": "mute()"}'))["tool"] == "mute"
    assert normalize(parse('{"tool": "play_music", "args": {}}'))["tool"] == "media_play_pause"
    assert normalize(parse('{"tool": "open_app", "args": {"app": "github.com"}}')) == {"tool": "open_url", "args": {"url": "github.com"}}
    assert normalize(parse('{"tool": "open_app", "args": {"app": "Spotify"}}'))["tool"] == "open_app"


def test_close_everything_is_the_careful_close():
    eng, ex, client, said, fb = make_agent([[("close_all", {})], [("finish", {"summary": "Closed what I opened."})]])
    eng.on_complete(1, "hey monster close everything")
    assert client.seen and said[-1].startswith("Closed what I opened.")
    from lazymonster.grammar import Grammar
    assert Grammar().parse("close all windows").name == "close_all"
    assert Grammar().parse("close notepad").name == "close_app"


def test_monster_wont_close_itself():
    from lazymonster.guards import is_self_name
    from lazymonster.npu_brain import normalize
    assert is_self_name("Lazy-Monster") and is_self_name("yourself") and not is_self_name("notepad")
    assert normalize({"tool": "close_app", "args": {"app": "everything"}})["tool"] == "hand_off"


# ---- 1.7.0: Brain-Break -------------------------------------------------------------------------
def test_brain_break_needs_two_misses_and_comes_back():
    from lazymonster.brainbreak import BrainBreak
    states, net = [], [False, False, False, True]
    bb = BrainBreak(states.append, check=lambda: net.pop(0))
    bb.tick(); assert states == [] and not bb.offline           # one miss is not an outage
    bb.tick(); assert states == [True] and bb.offline
    bb.tick(); bb.tick(); assert states == [True, False] and not bb.offline


def test_offline_simple_things_work_and_big_ones_wait():
    from lazymonster.brainbreak import BrainBreak
    from lazymonster.intents import validate
    eng, ex, client, said, fb = make_agent([])
    agent = eng.worker.agent
    bb = BrainBreak(lambda on: None, check=lambda: False); bb.tick(); bb.tick()
    agent.brain_break = bb
    class Q:
        def handle(self, task):
            return (validate("open_app", {"app": "Notepad"}, source="agent"), "Opening Notepad.", 0.3) if "notepad" in task else None
    agent.quick = Q()
    agent.run("open notepad")
    assert said[-1] == "Opening Notepad." and client.seen == []
    agent.run("research the latest nvidia news")
    assert "Brain-Break" in said[-1] and bb.waiting == ["research the latest nvidia news"] and client.seen == []


# ---- 1.7.3: it doesn't hear itself ------------------------------------------------------------------
def test_echo_guard_drops_its_own_words():
    from lazymonster.echo import EchoGuard, profile
    t = [100.0]
    g = EchoGuard(clock=lambda: t[0])
    g.record("I opened the cafe site in Chrome. Want me to update the menu?")
    assert g.is_echo("want me to update the menu") and g.is_echo("opened the cafe site in chrome")
    assert not g.is_echo("yes please do that") and not g.is_echo("open notepad") and not g.is_echo("update the menu")
    t[0] += 20
    assert not g.is_echo("want me to update the menu")        # long after: that's you
    assert profile("Intel(R) Display Audio (HDMI)")["tail"] == 0.9 and profile("Speakers (Realtek(R) Audio)")["kind"] == "laptop"
    assert profile("Headphones (Sony WH-1000XM5)")["kind"] == "headphones"


def test_own_echo_never_reaches_a_running_task():
    from lazymonster.echo import EchoGuard
    eng, ex, client, said, fb = make_agent([])
    eng.echo = EchoGuard()
    eng.echo.record("Writing the snake game now, this takes about a minute")
    eng.worker.busy.set()
    heard = []
    eng.worker.agent.hear = heard.append
    eng.on_complete(5, "writing the snake game now")
    assert heard == []
    eng.on_complete(6, "make the snake faster")
    assert heard == ["make the snake faster"]
    eng.worker.busy.clear()


def test_scrap_of_audio_during_task_is_not_you():
    eng, ex, client, said, fb = make_agent([])
    eng.verify = lambda t0: (True, -1.0)                      # too short to judge
    eng.worker.busy.set()
    heard = []
    eng.worker.agent.hear = heard.append
    eng.on_complete(7, "okay")
    assert heard == []
    eng.worker.busy.clear()


def test_your_reply_after_a_greeting_is_heard():
    from lazymonster.echo import EchoGuard
    eng, ex, client, said, fb = make_agent([[("finish", {"summary": "Opened it."})]])
    eng.echo = EchoGuard()
    eng.echo.record("Hi Andy, what can I do for you?")
    for g in ("hey monster can you", "hey monster can you open", "what"):
        assert not eng.echo.is_echo(g)
    eng.on_partial(9, "hey monster can you")
    eng.on_complete(9, "hey monster can you open notepad and write a note")
    assert client.seen                                          # the request reached the brain


def test_apple_quick_brain_uses_the_same_rules(monkeypatch):
    import sys, types
    from lazymonster import npu_brain as nb
    fake = types.SimpleNamespace(load=lambda repo: ("model", types.SimpleNamespace(apply_chat_template=lambda m, add_generation_prompt, tokenize: "P")),
                                 generate=lambda model, tok, prompt, max_tokens: '{"tool": "play_music", "args": {}}')
    monkeypatch.setitem(sys.modules, "mlx_lm", fake)
    qb = nb.MLXQuickBrain("mlx-community/Qwen2.5-1.5B-Instruct-4bit")
    intent, say, secs = qb.handle("play some music")
    assert intent.name == "media_play_pause" and qb.device == "Apple GPU (MLX)"


def test_mac_gpu_from_ioreg(monkeypatch):
    from lazymonster import sysinfo
    class R:
        stdout = '"PerformanceStatistics" = {"Device Utilization %"=37,"In use system memory"=4294967296}'
    monkeypatch.setattr(sysinfo.subprocess, "run", lambda *a, **k: R())
    assert sysinfo._mac_gpu() == {"gpu3d": 37.0, "compute": 0.0, "shared_gb": 4.3}
