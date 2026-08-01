"""Built-in and user-defined encoder preset helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ENCODE_PRESET_NAMES = (
    "Fast",
    "Balanced",
    "High Quality",
    "Extreme",
)

ENCODE_PRESET_PARAMETERS = {
    "x265": {
        "Fast": "--preset fast --crf 20 --aq-mode 2 --bframes 8 --ref 4 --me 2 --subme 2",
        "Balanced": "--preset slower --crf 18 --aq-mode 3 --bframes 8 --ref 5 --me 3 --subme 4",
        "High Quality": "--preset slower --crf 16 --aq-mode 3 --bframes 8 --psy-rd 2.0 --psy-rdoq 1.0 --deblock -1:-1 --rc-lookahead 60 --ref 6 --subme 5",
        "Extreme": "--preset placebo --crf 14 --aq-mode 3 --aq-strength 1.0 --cbqpoffs -2 --crqpoffs -2 --bframes 12 --b-adapt 2 --ref 6 --rc-lookahead 120 --lookahead-threads 0 --psy-rd 2.5 --psy-rdoq 2.0 --rdoq-level 2 --deblock -2:-2 --qcomp 0.65 --merange 57 --no-sao --no-strong-intra-smoothing",
    },
    "x264": {
        "Fast": "--preset fast --crf 20 --profile high --level 4.1 --bframes 4 --ref 4",
        "Balanced": "--preset medium --crf 18 --profile high --level 4.1 --bframes 6 --ref 5 --deblock -1:-1",
        "High Quality": "--preset slow --crf 16 --profile high --level 4.1 --bframes 8 --ref 6 --deblock -1:-1 --aq-mode 2",
        "Extreme": "--preset veryslow --crf 14 --profile high --level 4.1 --bframes 10 --ref 8 --aq-mode 2 --trellis 2",
    },
    "svtav1": {
        "Fast": "--preset 10 --crf 32 --keyint 240 --tune 0",
        "Balanced": "--preset 6 --crf 24 --keyint 240 --tune 0",
        "High Quality": "--preset 4 --crf 20 --keyint 240 --tune 0 --film-grain 4",
        "Extreme": "--preset 2 --crf 16 --keyint 240 --tune 0 --film-grain 0 --aq-mode 2",
    },
}


@dataclass(frozen=True)
class UserEncodePreset:
    encoder: str
    name: str
    parameters: str


def encode_presets_for_encoder(
        encoder: str,
        user_presets: Iterable[UserEncodePreset] = (),
) -> dict[str, str]:
    """Return ordered built-in presets followed by presets owned by one encoder."""
    normalized_encoder = str(encoder or "").strip().lower()
    presets = dict(ENCODE_PRESET_PARAMETERS.get(
        normalized_encoder,
        ENCODE_PRESET_PARAMETERS["x265"],
    ))
    for preset in user_presets:
        if preset.encoder == normalized_encoder:
            presets[preset.name] = preset.parameters
    return presets


def encode_preset_parameters(
        encoder: str,
        preset: str,
        user_presets: Iterable[UserEncodePreset] = (),
) -> str:
    """Return parameters for a built-in or user-defined encoder preset."""
    return encode_presets_for_encoder(encoder, user_presets).get(
        str(preset or ""),
        "",
    )


__all__ = [
    "ENCODE_PRESET_NAMES",
    "ENCODE_PRESET_PARAMETERS",
    "UserEncodePreset",
    "encode_preset_parameters",
    "encode_presets_for_encoder",
]
