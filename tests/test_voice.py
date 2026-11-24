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


def test_speech_reads_only_the_latest_persona_reply_in_its_voice():
    c, io = make()
    send(c, "a", "is virtue teachable", persona="socrates")
    t = tid(c, "a")
    first = "A fair question."
    r = c.post(f"/threads/{t}/speech", json={"text": first})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == silent_wav()
    assert io.spoken[-1][0] == first and io.spoken[-1][1] == "ash" and "café" in io.spoken[-1][2]
    assert c.post(f"/threads/{t}/speech", json={"text": "Read anything I like"}).json()["error"]["code"] == "not_in_reply"
    assert c.post(f"/threads/{t}/speech", json={"text": "x" * 601}).status_code == 400


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
    assert b"".join(v.speak("Hi.", "ash", "Warm.")) == b"mp3"
    method, url, kw = seen["stream"]
    assert url.endswith("/audio/speech") and kw["json"] == {"model": "gpt-4o-mini-tts", "voice": "ash", "input": "Hi.",
                                                            "response_format": "mp3", "instructions": "Warm."}
