"""Voice (design doc 7.6, FR-08, FR-09, ADR-14): speech-to-text in, text-to-speech out, around
the ordinary text turn. Safety, retrieval and the quote check do not change.

Two providers over plain HTTP (no SDKs, to keep the Vercel bundle lean), picked by
config.yaml voice.provider: ElevenLabs (Scribe in, Flash or Multilingual voices out) or OpenAI
(gpt-4o-mini-transcribe and gpt-4o-mini-tts, announced for shutdown in early 2027, after the
course). Either way the clip is sent to the transcription API and dropped: nothing is written
to disk or logs here (NFR-16). ElevenLabs keeps its own request history by default; its
zero-retention mode (enable_logging=false) is for enterprise accounts only and is refused
otherwise.

speak(text, persona) uses the persona config's voice for that provider: `voice.elevenlabs`
(a voice id) or `voice.name` plus `voice.style` (OpenAI follows a one-line style; ElevenLabs
voices carry their own character and take none).
"""

from __future__ import annotations

import io
import struct
from collections.abc import Iterator

import logging

import httpx

from app.config import secret

log = logging.getLogger(__name__)


def upstream_error(e: Exception) -> str:
    """A short, key-free description of a failed provider call, for the server log."""
    r = getattr(e, "response", None)
    if r is None:
        return type(e).__name__
    try:
        detail = r.json().get("detail") or r.json().get("error") or {}
        if isinstance(detail, dict):
            detail = detail.get("status") or detail.get("code") or detail.get("message") or ""
        detail = str(detail)[:160]
    except Exception:
        detail = ""
    return f"HTTP {r.status_code} {detail}".strip()

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

    def speak(self, text: str, persona) -> Iterator[bytes]:
        """mp3 bytes for `text`, streamed as they arrive."""
        body = {"model": self.speech_model, "voice": persona.voice, "input": text, "response_format": "mp3"}
        if persona.voice_style:
            body["instructions"] = persona.voice_style
        with httpx.stream("POST", f"{API}/speech", headers=self._headers(), json=body, timeout=self.timeout_s) as r:
            r.raise_for_status()
            yield from r.iter_bytes()


ELEVEN = "https://api.elevenlabs.io/v1"
ELEVEN_FALLBACK_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # George, a premade voice every account has


class ElevenLabsVoice:
    media_type = "audio/mpeg"

    def __init__(self, tts_model: str = "eleven_flash_v2_5", stt_model: str = "scribe_v2", timeout_s: float = 20.0):
        self.tts_model = tts_model
        self.stt_model = stt_model
        self.timeout_s = timeout_s

    def _headers(self) -> dict:
        return {"xi-api-key": secret("ELEVENLABS_API_KEY")}

    def transcribe(self, audio: bytes, content_type: str) -> dict:
        name = clip_name(content_type) or "clip.webm"
        r = httpx.post(f"{ELEVEN}/speech-to-text", headers=self._headers(), timeout=self.timeout_s,
                       data={"model_id": self.stt_model, "tag_audio_events": "false"},
                       files={"file": (name, audio, content_type.split(";")[0])})
        r.raise_for_status()
        j = r.json()
        return {"text": (j.get("text") or "").strip(), "language": j.get("language_code")}

    def _stream(self, voice_id: str, text: str):
        return httpx.stream("POST", f"{ELEVEN}/text-to-speech/{voice_id}/stream", headers=self._headers(),
                            params={"output_format": "mp3_44100_128"},
                            json={"text": text, "model_id": self.tts_model}, timeout=self.timeout_s)

    def speak(self, text: str, persona) -> Iterator[bytes]:
        voice_id = persona.elevenlabs_voice or ELEVEN_FALLBACK_VOICE
        with self._stream(voice_id, text) as r:
            if r.status_code in (400, 401, 404, 422) and voice_id != ELEVEN_FALLBACK_VOICE:
                # A library voice not in this account (or not allowed on this plan): use the premade fallback.
                log.warning("ElevenLabs voice %s refused (%s); using the fallback voice", voice_id, r.status_code)
            else:
                r.raise_for_status()
                yield from r.iter_bytes()
                return
        with self._stream(ELEVEN_FALLBACK_VOICE, text) as r:
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

    def speak(self, text: str, persona) -> Iterator[bytes]:
        self.spoken.append((text, persona.voice, persona.voice_style))
        yield silent_wav()
