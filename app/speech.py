"""Voice (design doc 7.6, FR-08, FR-09, ADR-14): speech-to-text in, text-to-speech out, around
the ordinary text turn. Safety, retrieval and the quote check do not change.

OpenAI's audio API over plain HTTP (no SDK, to keep the Vercel bundle lean). The clip is sent
to the transcription API and dropped: nothing is written to disk or logs (NFR-16).

gpt-4o-mini-transcribe and gpt-4o-mini-tts are announced for shutdown in early 2027
(transcription 2027-02-26, speech 2027-01-06), after the course ends; the model names live in
config.yaml so they can be swapped.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Iterator

import httpx

from app.config import secret

API = "https://api.openai.com/v1/audio"
MAX_CLIP_BYTES = 4 * 1024 * 1024          # about 60 s of compressed speech
MAX_SPEECH_CHARS = 600                    # one sentence or a few; the browser asks sentence by sentence
CLIP_TYPES = {"audio/webm": "clip.webm", "audio/mp4": "clip.mp4", "audio/mpeg": "clip.mp3",
              "audio/ogg": "clip.ogg", "audio/wav": "clip.wav", "audio/x-m4a": "clip.m4a"}


def clip_name(content_type: str) -> str | None:
    """A file name the API accepts for this upload type, or None if it is not audio we take."""
    return CLIP_TYPES.get(content_type.split(";")[0].strip().lower())


class OpenAIVoice:
    def __init__(self, transcribe_model: str, speech_model: str, timeout_s: float = 20.0):
        self.transcribe_model = transcribe_model
        self.speech_model = speech_model
        self.timeout_s = timeout_s

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {secret('OPENAI_API_KEY')}"}

    def transcribe(self, audio: bytes, content_type: str) -> dict:
        name = clip_name(content_type) or "clip.webm"
        r = httpx.post(f"{API}/transcriptions", headers=self._headers(), timeout=self.timeout_s,
                       data={"model": self.transcribe_model, "response_format": "json"},
                       files={"file": (name, audio, content_type.split(";")[0])})
        r.raise_for_status()
        return {"text": (r.json().get("text") or "").strip(), "language": r.json().get("language")}

    def speak(self, text: str, voice: str, style: str) -> Iterator[bytes]:
        """mp3 bytes for `text`, streamed as they arrive."""
        body = {"model": self.speech_model, "voice": voice, "input": text, "response_format": "mp3"}
        if style:
            body["instructions"] = style
        with httpx.stream("POST", f"{API}/speech", headers=self._headers(), json=body, timeout=self.timeout_s) as r:
            r.raise_for_status()
            yield from r.iter_bytes()


# ---------- offline stand-ins (tests and PHILOCAFE_FAKE=1) ----------

def silent_wav(seconds: float = 0.4, rate: int = 8000) -> bytes:
    """A short silent WAV, so the offline demo has something real to play."""
    frames = int(seconds * rate)
    out = io.BytesIO()
    out.write(b"RIFF" + struct.pack("<I", 36 + frames * 2) + b"WAVEfmt ")
    out.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    out.write(b"data" + struct.pack("<I", frames * 2) + b"\x00\x00" * frames)
    return out.getvalue()


class FakeVoiceIO:
    media_type = "audio/wav"

    def __init__(self, transcript: str = "Is virtue something we can teach?"):
        self.transcript = transcript
        self.spoken: list[tuple[str, str, str]] = []

    def transcribe(self, audio: bytes, content_type: str) -> dict:
        return {"text": self.transcript, "language": "english"}

    def speak(self, text: str, voice: str, style: str) -> Iterator[bytes]:
        self.spoken.append((text, voice, style))
        yield silent_wav()
