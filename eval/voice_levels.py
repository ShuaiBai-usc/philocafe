"""Check that the read-aloud voices come out at an even volume (design doc 7.6).

Asks ElevenLabs for one short sentence in every voice the persona configs name (the default
voice and each language voice), as raw 16 kHz PCM, and prints each voice's loudness with the
same measure the web app uses before playing a clip (gated RMS over 50 ms frames, silence
below -50 dBFS left out), the gain the app applies and the level that results.

    .venv/bin/python eval/voice_levels.py             # needs ELEVENLABS_API_KEY in .env

About 450 characters in all (under 1% of the Creator plan's monthly credits).
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import load_config, secret  # noqa: E402
from app.personas import load_personas  # noqa: E402

# Must match TARGET_DB, MAX_GAIN_DB and GATE in ui/web/template.html.
TARGET_DB, MAX_GAIN_DB, GATE = -20.0, 18.0, 1e-5
SAMPLES = {None: "That is a fair question. What do you think makes a life a good one?",
           "zh": "这是个好问题。你觉得什么样的生活才算好？"}
RATE = 16000


def loudness_db(pcm: bytes, rate: int = RATE) -> float | None:
    samples = [s / 32768 for s in struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) // 2 * 2])]
    n = round(rate * 0.05)
    energies = [sum(x * x for x in samples[i:i + n]) / n for i in range(0, len(samples) - n + 1, n)]
    voiced = [e for e in energies if e > GATE]
    return 10 * math.log10(sum(voiced) / len(voiced)) if voiced else None


def gain_db(db: float | None) -> float:
    return 0.0 if db is None else max(-MAX_GAIN_DB, min(MAX_GAIN_DB, TARGET_DB - db))


def synth(voice_id: str, text: str, model: str, language: str | None) -> bytes:
    body = {"text": text, "model_id": model}
    if language and model in ("eleven_flash_v2_5", "eleven_turbo_v2_5"):
        body["language_code"] = language
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}", params={"output_format": "pcm_16000"},
                   headers={"xi-api-key": secret("ELEVENLABS_API_KEY")}, json=body, timeout=60)
    r.raise_for_status()
    return r.content


def main() -> None:
    model = load_config().elevenlabs_tts_model
    rows = []
    for p in load_personas().values():
        voices = {None: p.elevenlabs_voice, **p.elevenlabs_by_language}
        for lang, voice_id in voices.items():
            if not voice_id:
                continue
            try:
                db = loudness_db(synth(voice_id, SAMPLES.get(lang, SAMPLES[None]), model, lang))
            except httpx.HTTPStatusError as e:
                print(f"{p.name} {lang or 'en'} {voice_id}: HTTP {e.response.status_code} (add the voice to My Voices?)")
                continue
            rows.append((p.name, lang or "en", voice_id, db))
    print(f"\nmodel {model}; target {TARGET_DB:.0f} dB\n")
    print(f"{'persona':13s} {'lang':4s} {'voice':22s} {'measured':>9s} {'gain':>8s} {'played at':>10s}")
    for name, lang, voice_id, db in rows:
        g = gain_db(db)
        shown = "silent" if db is None else f"{db:9.1f}"
        print(f"{name:13s} {lang:4s} {voice_id:22s} {shown:>9s} {g:+8.1f} {(db or 0) + g:10.1f}")
    measured = [db for *_, db in rows if db is not None]
    if measured:
        played = [d + gain_db(d) for d in measured]
        print(f"\nspread before levelling: {max(measured) - min(measured):.1f} dB; after: {max(played) - min(played):.1f} dB")

if __name__ == "__main__":
    main()
