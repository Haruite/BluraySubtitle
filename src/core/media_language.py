"""Language-code normalization for media track comparison."""

import pycountry


def normalize_track_language(raw: object) -> str:
    primary = str(raw or '').strip().lower().replace('_', '-').split('-', 1)[0]
    if not primary:
        return 'und'
    # Keep the application's shared Chinese-language track grouping.
    if primary in ('zho', 'chi', 'cmn', 'yue', 'nan', 'zh', 'chs', 'cht'):
        return 'zho'
    language = (
        pycountry.languages.get(alpha_2=primary)
        if len(primary) == 2 else
        pycountry.languages.get(alpha_3=primary) or pycountry.languages.get(bibliographic=primary)
    )
    return language.alpha_3 if language else primary
