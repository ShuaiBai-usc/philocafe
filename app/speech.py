"""Voice (design doc 7.6, FR-08, FR-09, ADR-14): speech-to-text in, text-to-speech out, around
the ordinary text turn. Safety, retrieval and the quote check do not change.

Two providers over plain HTTP (no SDKs, to keep the Vercel bundle lean), picked by
config.yaml voice.provider: ElevenLabs (Scribe in, Flash or Multilingual voices out) or OpenAI
(gpt-4o-mini-transcribe and gpt-4o-mini-tts, announced for shutdown in early 2027, after the
course). Either way the clip is sent to the transcription API and dropped: nothing is written
to disk or logs here (NFR-16). ElevenLabs keeps its own request history by default; its
zero-retention mode (enable_logging=false) is for enterprise accounts only and is refused
otherwise.

speak(text, persona, mood) uses the persona config's voice for that provider: `voice.elevenlabs`
(a voice id), or `voice.elevenlabs_by_language[<lang>]` when the sentence is Chinese, Japanese or
Korean (replies follow the user's language), or `voice.name` plus `voice.style` for OpenAI,
whose voices read every language. The reply's mood (7.5) sets the tone:
- ElevenLabs Flash / Multilingual: voice settings per mood (stability, style, speed), blended
  from attentive by the mood's intensity.
- ElevenLabs v3: an audio tag at the start of each sentence ([curious], [thoughtfully], ...).
- OpenAI: a tone line added to the persona's style instruction.
While the mood is locked (tier 2 and up, exit, support mode; FR-34) the tone is calm and level.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Iterator

import logging
import re

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

    def speak(self, text: str, persona, mood: dict | None = None) -> Iterator[bytes]:
        """mp3 bytes for `text`, streamed as they arrive."""
        body = {"model": self.speech_model, "voice": persona.voice, "input": text, "response_format": "mp3"}
        if instructions := openai_instructions(persona.voice_style, mood):
            body["instructions"] = instructions
        with httpx.stream("POST", f"{API}/speech", headers=self._headers(), json=body, timeout=self.timeout_s) as r:
            r.raise_for_status()
            yield from r.iter_bytes()


# ---------- language of what is read (7.6) ----------
# Replies come in the language of the user's message, so each sentence is checked on its own.
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
KANA = re.compile(r"[\u3040-\u30ff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")
LETTER = re.compile(r"\w", re.UNICODE)
# Flash and Turbo v2.5 take a language_code that holds them to one language; other models refuse it.
LANGUAGE_CODE_MODELS = ("eleven_flash_v2_5", "eleven_turbo_v2_5")


def speech_language(text: str) -> str | None:
    """'zh', 'ja' or 'ko' when that script makes up a good part of the sentence, else None
    (the persona's default voice, which reads English and other Latin-script languages)."""
    letters = len(LETTER.findall(text)) or 1
    if len(KANA.findall(text)) / letters > 0.1:
        return "ja"
    if len(HANGUL.findall(text)) / letters > 0.3:
        return "ko"
    if len(HAN.findall(text)) / letters > 0.3:
        return "zh"
    return None


# ---------- tone from the mood (7.5, 7.6) ----------
# Settings that move with the mood; similarity_boost stays at the ElevenLabs default.
TONE_SETTINGS = {
    "attentive": {"stability": 0.60, "style": 0.05, "speed": 0.97},
    "curious":   {"stability": 0.45, "style": 0.25, "speed": 1.00},
    "amused":    {"stability": 0.35, "style": 0.45, "speed": 1.04},
    "pleased":   {"stability": 0.45, "style": 0.30, "speed": 1.00},
    "pondering": {"stability": 0.55, "style": 0.15, "speed": 0.92},
    "skeptical": {"stability": 0.50, "style": 0.30, "speed": 0.97},
    "wry":       {"stability": 0.40, "style": 0.35, "speed": 1.00},
    "grave":     {"stability": 0.65, "style": 0.10, "speed": 0.90},
}
TONE_LOCKED = {"stability": 0.75, "style": 0.0, "speed": 0.90}
V3_TAGS = {"curious": "[curious]", "amused": "[amused]", "pleased": "[warmly]", "pondering": "[thoughtfully]",
           "skeptical": "[skeptically]", "wry": "[dryly]", "grave": "[seriously]", "attentive": ""}
V3_LOCKED_TAG = "[calmly]"
OPENAI_TONE = {"curious": "a little more curious and lively", "amused": "lightly amused, a smile in the voice",
               "pleased": "warm and pleased", "pondering": "slower and thoughtful, with small pauses",
               "skeptical": "gently skeptical, unhurried", "wry": "dry and wry", "grave": "grave and measured",
               "attentive": "calm and attentive"}
OPENAI_LOCKED = "Speak calmly, slowly and evenly, with no humour or irony."


def tone_settings(mood: dict | None) -> dict:
    """ElevenLabs voice settings for a reply's mood (Flash and Multilingual models)."""
    if not mood:
        return {}
    if mood.get("locked"):
        return dict(TONE_LOCKED, similarity_boost=0.75)
    calm, target = TONE_SETTINGS["attentive"], TONE_SETTINGS.get(mood.get("label"), TONE_SETTINGS["attentive"])
    w = min(1.0, 0.4 + float(mood.get("intensity", 0.5)))         # a faint mood stays near calm
    out = {k: round(calm[k] + (target[k] - calm[k]) * w, 3) for k in calm}
    return dict(out, similarity_boost=0.75)


def v3_text(text: str, mood: dict | None) -> str:
    if not mood:
        return text
    tag = V3_LOCKED_TAG if mood.get("locked") else V3_TAGS.get(mood.get("label"), "")
    return f"{tag} {text}" if tag else text


def openai_instructions(style: str, mood: dict | None) -> str:
    if not mood:
        return style
    tone = OPENAI_LOCKED if mood.get("locked") else f"Right now sound {OPENAI_TONE.get(mood.get('label'), 'calm')}."
    return f"{style} {tone}".strip()


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

    def body(self, text: str, mood: dict | None, language: str | None = None) -> dict:
        out = self._body(text, mood)
        if language and self.tts_model in LANGUAGE_CODE_MODELS:
            out["language_code"] = language
        return out

    def _body(self, text: str, mood: dict | None) -> dict:
        if self.tts_model.startswith("eleven_v3"):
            # v3 takes its tone from audio tags; its stability has three steps (0, 0.5, 1).
            out = {"text": v3_text(text, mood), "model_id": self.tts_model}
            if mood:
                out["voice_settings"] = {"stability": 1.0 if mood.get("locked") else 0.5}
            return out
        out = {"text": text, "model_id": self.tts_model}
        if settings := tone_settings(mood):
            out["voice_settings"] = settings
        return out

    def _stream(self, voice_id: str, body: dict):
        return httpx.stream("POST", f"{ELEVEN}/text-to-speech/{voice_id}/stream", headers=self._headers(),
                            params={"output_format": "mp3_44100_128"}, json=body, timeout=self.timeout_s)

    def speak(self, text: str, persona, mood: dict | None = None) -> Iterator[bytes]:
        language = speech_language(text)
        voice_id = (persona.elevenlabs_by_language.get(language or "") or persona.elevenlabs_voice
                    or ELEVEN_FALLBACK_VOICE)
        body = self.body(text, mood, language)
        with self._stream(voice_id, body) as r:
            if r.status_code in (400, 401, 404, 422) and voice_id != ELEVEN_FALLBACK_VOICE:
                # A library voice not in this account (or not allowed on this plan): use the premade fallback.
                log.warning("ElevenLabs voice %s refused (%s); using the fallback voice", voice_id, r.status_code)
            else:
                r.raise_for_status()
                yield from r.iter_bytes()
                return
        with self._stream(ELEVEN_FALLBACK_VOICE, body) as r:
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
        self.spoken: list[tuple[str, str, str, dict | None]] = []

    def transcribe(self, audio: bytes, content_type: str) -> dict:
        return {"text": self.transcript, "language": "english"}

    def speak(self, text: str, persona, mood: dict | None = None) -> Iterator[bytes]:
        self.spoken.append((text, persona.voice, persona.voice_style, mood))
        yield silent_wav()
