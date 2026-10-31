from __future__ import annotations

import io

from ..core import config

_model = None


def decode_waveform(audio: bytes):
    """Decode browser audio (webm/opus etc.) to a 16 kHz mono float32 waveform.

    Decoding here avoids faster-whisper's bundled av.open(...) call, whose
    keyword arguments can mismatch the installed PyAV version.
    """
    import numpy as np
    import av
    from av.audio.resampler import AudioResampler

    resampler = AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("The audio contained no decodable sound.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(audio: bytes) -> str:
    global _model
    if not config.VOICE_ENABLED:
        raise RuntimeError("Voice transcription is disabled in configuration.")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install faster-whisper to enable voice input; text chat remains available.") from exc
    if _model is None:
        _model = WhisperModel(config.VOICE_MODEL, device="cpu", compute_type="int8")
    waveform = decode_waveform(audio)
    segments, _ = _model.transcribe(waveform, vad_filter=True, language=config.VOICE_LANGUAGE,
                                    condition_on_previous_text=False)
    return " ".join(segment.text.strip() for segment in segments).strip()
