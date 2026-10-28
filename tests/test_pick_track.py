"""Run: python tests/test_pick_track.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("yt", Path(__file__).parents[1] / "skills" / "youtube" / "yt.py")
yt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yt)

EN_ORIGINAL = [{"language": "en-US", "format_note": "American English - original (original)"}]
TRANSLATIONS = {l: [] for l in ("ar", "bn", "en", "it", "fr")}


def meta(language=None, formats=(), manual=(), auto=()):
    return {"language": language, "formats": list(formats),
            "subtitles": {l: [] for l in manual}, "automatic_captions": {l: [] for l in auto}}


cases = [
    # Uploaded Arabic subtitles must not beat the English speech track.
    (meta("en-US", EN_ORIGINAL, manual=["ar"], auto=[*TRANSLATIONS, "en-orig"]), ("en-orig", "auto", False)),
    # Declared language wrong: the "original" audio track wins over the "ar" machine translation.
    (meta("ar", EN_ORIGINAL, auto=[*TRANSLATIONS, "en-orig"]), ("en-orig", "auto", False)),
    # AI-dubbed video: the Arabic dub's speech track isn't the original.
    (meta("en-US", EN_ORIGINAL, auto=["ar-orig", "bn-orig", *TRANSLATIONS, "en-orig"]), ("en-orig", "auto", False)),
    # No original speech track: fall back to the translation into the original language, and say so.
    (meta("en-US", EN_ORIGINAL, auto=["fr-FR-orig", *TRANSLATIONS]), ("en", "auto", True)),
    # Manual subtitles in the original language beat auto captions.
    (meta("it", manual=["en", "it"], auto=[*TRANSLATIONS, "it-orig"]), ("it", "manual", False)),
    # No language info at all: English, flagged as translated since it isn't "-orig".
    (meta(None, auto=[*TRANSLATIONS]), ("en", "auto", True)),
    (meta(None), (None, None, False)),
]
for m, want in cases:
    got = yt.pick_track(m)
    assert got == want, f"{m}: got {got}, want {want}"
print(f"ok: {len(cases)} cases")
