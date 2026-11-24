"""Voice conversation (design doc 7.6, FR-08, FR-09, FR-35) over offline stand-ins."""

from app.auth import Tokens
from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps
from app.server import create_app
from app.speech import FakeVoiceIO, clip_name, silent_wav
from tests.helpers import send, signed_in, tid

REPLY = FAKE_QUOTING_REPLY.replace('<q id="socrates-meno-00000000">', "“").replace("</q>", "”")


def make(voice=True):
    io = FakeVoiceIO()
    deps = fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")]), voice_io=io if voice else None)
    return signed_in(create_app(deps, tokens=Tokens("k"))), io


def test_me_says_whether_voice_is_on():
    assert make()[0].get("/me").json()["voice"] is True
    assert make(voice=False)[0].get("/me").json()["voice"] is False


def test_transcribe_returns_text_and_starts_no_turn():
    c, _ = make()
    t = tid(c)
    r = c.post(f"/threads/{t}/transcribe", content=b"\x1a\x45\xdf\xa3 fake webm", headers={"Content-Type": "audio/webm;codecs=opus"})
    assert r.status_code == 200 and r.json()["text"] == "Is virtue something we can teach?"
    assert c.get(f"/threads/{t}").json()["messages"] == []
    assert c.post(f"/threads/{t}/transcribe", content=b"x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert c.post(f"/threads/{t}/transcribe", content=b"", headers={"Content-Type": "audio/mp4"}).status_code == 400
    big = b"0" * (4 * 1024 * 1024 + 1)
    assert c.post(f"/threads/{t}/transcribe", content=big, headers={"Content-Type": "audio/mp4"}).status_code == 413


def test_speech_reads_only_persona_replies_in_its_voice():
    c, io = make()
    send(c, "a", "is virtue teachable", persona="socrates")
    t = tid(c, "a")
    first = "A fair question."
    r = c.post(f"/threads/{t}/speech", json={"text": first})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == silent_wav()
    assert io.spoken[-1][0] == first and io.spoken[-1][1] == "ash" and "café" in io.spoken[-1][2]
    assert c.post(f"/threads/{t}/speech", json={"text": "Read anything I like"}).json()["error"]["code"] == "not_in_reply"
    assert c.post(f"/threads/{t}/speech", json={"text": "x" * 601}).status_code == 400
    assert c.post(f"/threads/{t}/speech", json={"text": "is virtue teachable"}).status_code == 400   # the user's own words
    send(c, "a", "and courage?", persona="socrates")
    assert c.post(f"/threads/{t}/speech", json={"text": first}).status_code == 200   # an earlier reply still reads


def test_nothing_is_read_aloud_in_support_mode():
    c, io = make()
    send(c, "a", "TEST_TIER3")
    t = tid(c, "a")
    r = c.post(f"/threads/{t}/speech", json={"text": "Let's take a moment."})
    assert r.status_code == 409 and not io.spoken


def test_voice_off_and_other_users():
    c, _ = make(voice=False)
    t = tid(c)
    assert c.post(f"/threads/{t}/transcribe", content=b"x", headers={"Content-Type": "audio/webm"}).status_code == 501
    c2, _ = make()
    send(c2, "a", "hello")
    other = signed_in(c2.app, "someone")
    assert other.post(f"/threads/{tid(c2, 'a')}/speech", json={"text": "A fair question."}).status_code == 404


def test_clip_types():
    assert clip_name("audio/webm;codecs=opus") == "clip.webm" and clip_name("audio/mp4") == "clip.mp4"
    assert clip_name("video/mp4") is None


def test_openai_requests_are_built_as_the_api_expects(monkeypatch):
    import httpx
    from app import speech
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"text": " hello there "}
        def iter_bytes(self): yield b"mp3"
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def post(url, **kw):
        seen["post"] = (url, kw)
        return Resp()

    def stream(method, url, **kw):
        seen["stream"] = (method, url, kw)
        return Resp()

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "stream", stream)
    v = speech.OpenAIVoice("gpt-4o-mini-transcribe", "gpt-4o-mini-tts")
    assert v.transcribe(b"abc", "audio/mp4")["text"] == "hello there"
    url, kw = seen["post"]
    assert url.endswith("/audio/transcriptions") and kw["data"]["model"] == "gpt-4o-mini-transcribe"
    assert kw["files"]["file"][0] == "clip.mp4" and kw["headers"]["Authorization"] == "Bearer sk-test"
    from app.personas import load_personas
    socrates = load_personas()["socrates"]
    assert b"".join(v.speak("Hi.", socrates)) == b"mp3"
    method, url, kw = seen["stream"]
    assert url.endswith("/audio/speech") and kw["json"]["voice"] == "ash" and kw["json"]["input"] == "Hi."
    assert kw["json"]["instructions"] == socrates.voice_style


def test_elevenlabs_requests_and_fallback_voice(monkeypatch):
    import httpx
    from app import speech
    from app.personas import load_personas
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi-test")
    calls = []

    class Resp:
        def __init__(self, status=200, body=None):
            self.status_code, self.body = status, body or {"text": " hi ", "language_code": "eng"}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)
        def json(self): return self.body
        def iter_bytes(self): yield b"mp3"
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(httpx, "post", lambda url, **kw: calls.append(("post", url, kw)) or Resp())
    statuses = iter([404, 200])
    monkeypatch.setattr(httpx, "stream", lambda m, url, **kw: calls.append(("stream", url, kw)) or Resp(next(statuses)))
    v = speech.ElevenLabsVoice()
    assert v.transcribe(b"x", "audio/webm;codecs=opus") == {"text": "hi", "language": "eng"}
    _, url, kw = calls[0]
    assert url.endswith("/speech-to-text") and kw["data"]["model_id"] == "scribe_v2" and kw["headers"]["xi-api-key"] == "xi-test"
    socrates = load_personas()["socrates"]
    assert b"".join(v.speak("Hello.", socrates)) == b"mp3"
    first, second = calls[1], calls[2]
    assert socrates.elevenlabs_voice in first[1] and speech.ELEVEN_FALLBACK_VOICE in second[1]
    assert second[2]["json"] == {"text": "Hello.", "model_id": "eleven_flash_v2_5"}


def test_provider_is_picked_by_config_and_key(monkeypatch):
    from dataclasses import replace
    from app.config import Config
    from app.deps import voice_io
    from app.speech import ElevenLabsVoice, OpenAIVoice
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    eleven = replace(Config(), voice_provider="elevenlabs")
    assert voice_io(eleven) is None
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert isinstance(voice_io(eleven), ElevenLabsVoice)
    assert voice_io(Config()) is None
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    assert isinstance(voice_io(Config()), OpenAIVoice)


def test_tone_follows_the_mood():
    from app.speech import ElevenLabsVoice, openai_instructions, tone_settings, TONE_LOCKED
    locked = {"label": "attentive", "intensity": 0.2, "locked": True}
    amused = {"label": "amused", "intensity": 0.6, "locked": False}
    faint = {"label": "amused", "intensity": 0.0, "locked": False}
    assert tone_settings(None) == {}
    assert tone_settings(locked)["stability"] == TONE_LOCKED["stability"] and tone_settings(locked)["style"] == 0
    strong, weak = tone_settings(amused), tone_settings(faint)
    assert strong["style"] > weak["style"] > 0.05 and strong["speed"] > 1.0
    flash = ElevenLabsVoice().body("Hm.", amused)
    assert flash["text"] == "Hm." and flash["voice_settings"] == strong
    v3 = ElevenLabsVoice(tts_model="eleven_v3")
    assert v3.body("Hm.", amused) == {"text": "[amused] Hm.", "model_id": "eleven_v3", "voice_settings": {"stability": 0.5}}
    assert v3.body("Hm.", locked)["text"] == "[calmly] Hm." and v3.body("Hm.", None) == {"text": "Hm.", "model_id": "eleven_v3"}
    assert "calmly" in openai_instructions("Warm.", locked) and "amused" in openai_instructions("Warm.", amused)


def test_speech_passes_the_replys_mood():
    c, io = make()
    send(c, "a", "is virtue teachable", persona="socrates")
    t = tid(c, "a")
    assert c.post(f"/threads/{t}/speech", json={"text": "A fair question."}).status_code == 200
    assert io.spoken[-1][3] == {"label": "pondering", "intensity": 0.7, "locked": False}
    msgs = c.get(f"/threads/{t}").json()["messages"]
    assert [m for m in msgs if m["role"] == "persona"][-1]["mood"]["label"] == "pondering"


def test_chinese_sentences_use_the_chinese_voice():
    from app.personas import load_personas
    from app.speech import ElevenLabsVoice, speech_language
    assert speech_language("你觉得什么样的生活才算好？") == "zh"
    assert speech_language("What makes a life good?") is None
    assert speech_language("我读过 Meno 这篇对话。") == "zh"
    assert speech_language("Socrates 说") is None or speech_language("Socrates 说") == "zh"
    assert speech_language("こんにちは、元気ですか") == "ja" and speech_language("안녕하세요 반갑습니다") == "ko"
    v = ElevenLabsVoice()
    assert v.body("你好。", None, "zh")["language_code"] == "zh"
    assert "language_code" not in ElevenLabsVoice(tts_model="eleven_multilingual_v2").body("你好。", None, "zh")
    socrates = load_personas()["socrates"]
    assert socrates.elevenlabs_by_language["zh"] and socrates.elevenlabs_by_language["zh"] != socrates.elevenlabs_voice


def test_speak_picks_the_voice_by_language(monkeypatch):
    import httpx
    from app import speech
    from app.personas import load_personas
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    urls = []

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def iter_bytes(self): yield b"mp3"
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(httpx, "stream", lambda m, url, **kw: urls.append((url, kw["json"])) or Resp())
    p = load_personas()["socrates"]
    b"".join(speech.ElevenLabsVoice().speak("什么是美德？", p))
    b"".join(speech.ElevenLabsVoice().speak("What is virtue?", p))
    assert p.elevenlabs_by_language["zh"] in urls[0][0] and urls[0][1]["language_code"] == "zh"
    assert p.elevenlabs_voice in urls[1][0] and "language_code" not in urls[1][1]
