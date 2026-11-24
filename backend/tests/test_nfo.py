from pathlib import Path

from driftwood.selection.nfo import (
    SubtitleTrack,
    decode_nfo,
    normalize_language,
    parse_nfo,
)

FIXTURES = Path(__file__).parent / "indexers" / "fixtures" / "torrentleech"


def nfo(name: str) -> str:
    return decode_nfo((FIXTURES / name).read_bytes())


def test_normalize_language() -> None:
    assert normalize_language("English") == "en"
    assert normalize_language("english (US)") == "en"
    assert normalize_language("ENG") == "en"
    assert normalize_language("en") == "en"
    assert normalize_language("ger") == "de"
    assert normalize_language("dut") == "nl"
    assert normalize_language("pt-BR") == "pt"
    assert normalize_language("English SDH") == "en"
    assert normalize_language("Spanish (Latin America)") == "es"
    assert normalize_language("DD5.1") is None
    assert normalize_language("") is None


def test_mediainfo_dump() -> None:
    info = parse_nfo(nfo("nfo_mediainfo.nfo"))
    assert info.subtitles_known
    assert info.subtitles == (
        SubtitleTrack("en", forced=True),
        SubtitleTrack("en", forced=False),
        SubtitleTrack("nl", forced=False),
    )
    assert info.audio_languages == ("en",)


def test_mediainfo_without_text_sections_means_no_subtitles() -> None:
    info = parse_nfo(
        "General\nFormat : Matroska\n\nVideo\nFormat : AVC\n\nAudio\nLanguage : French\n"
    )
    assert info.subtitles_known
    assert info.subtitles == ()
    assert info.audio_languages == ("fr",)


def test_scene_nfo_in_cp437_box_art() -> None:
    text = nfo("nfo_scene.nfo")
    assert "╔" in text  # decoded as CP437
    info = parse_nfo(text)
    assert info.subtitles_known
    assert info.subtitles == (
        SubtitleTrack("nl"),
        SubtitleTrack("sv"),
        SubtitleTrack("en", forced=True),
    )
    assert info.audio_languages == ("en",)


def test_scene_nfo_saying_none() -> None:
    info = parse_nfo(nfo("nfo_none.nfo"))
    assert info.subtitles_known
    assert info.subtitles == ()


def test_nfo_without_subtitle_info() -> None:
    info = parse_nfo("Greetings to all our friends\nEncoded with love\n")
    assert not info.subtitles_known


def test_utf8_nfo() -> None:
    assert decode_nfo("Subtitles: Français".encode()) == "Subtitles: Français"
    assert parse_nfo("Subtitles: Français, English").subtitles[-1] == SubtitleTrack("en")
