"""Tests unitarios para switch_bot.models.enums."""

import pytest

from switch_bot.models.enums import (
    EDLColor,
    MARKER_COLOR_MAP,
    MarkerType,
    SourceOrigin,
)


class TestMarkerType:
    """Verifica que MarkerType tenga todos los miembros requeridos."""

    def test_has_all_expected_members(self):
        expected = {
            "MANUAL_NOTE",
            "SCRIPT_MATCH",
            "SCRIPT_DEVIATION",
            "AI_PROMPT",
            "ENTRADA",
            "SALIDA",
            "TOS",
            "ERROR_DICCION",
            "CONFUSION",
            "REPETICION",
            "PANIC",
            "IMAGEN",
        }
        actual = {m.name for m in MarkerType}
        assert actual == expected

    def test_values_match_names(self):
        for member in MarkerType:
            assert member.value == member.name


class TestEDLColor:
    """Verifica que EDLColor tenga los colores de DaVinci Resolve."""

    def test_has_all_expected_colors(self):
        expected = {"Red", "Green", "Magenta", "Cyan", "Yellow", "Blue"}
        actual = {c.name for c in EDLColor}
        assert actual == expected

    def test_values_are_resolve_prefixed(self):
        for color in EDLColor:
            assert color.value.startswith("ResolveColor")

    def test_specific_color_values(self):
        assert EDLColor.Red.value == "ResolveColorRed"
        assert EDLColor.Green.value == "ResolveColorGreen"
        assert EDLColor.Magenta.value == "ResolveColorMagenta"
        assert EDLColor.Cyan.value == "ResolveColorCyan"
        assert EDLColor.Yellow.value == "ResolveColorYellow"
        assert EDLColor.Blue.value == "ResolveColorBlue"


class TestSourceOrigin:
    """Verifica que SourceOrigin tenga los orígenes esperados."""

    def test_has_all_expected_origins(self):
        expected = {"MANUAL", "AI", "AUTO", "ANOMALY"}
        actual = {s.name for s in SourceOrigin}
        assert actual == expected

    def test_values_match_names(self):
        for origin in SourceOrigin:
            assert origin.value == origin.name


class TestMarkerColorMap:
    """Verifica el mapeo de marcadores a colores según Req 13.3."""

    def test_red_markers(self):
        """Req 13.3: Red para MANUAL_NOTE, TOS, ERROR_DICCION, CONFUSION, REPETICION."""
        red_markers = {MarkerType.MANUAL_NOTE, MarkerType.TOS, MarkerType.ERROR_DICCION,
                       MarkerType.CONFUSION, MarkerType.REPETICION}
        for marker in red_markers:
            assert MARKER_COLOR_MAP[marker] == EDLColor.Red, (
                f"{marker.name} debería ser Red"
            )

    def test_green_markers(self):
        """Req 13.3: Green para SCRIPT_MATCH."""
        assert MARKER_COLOR_MAP[MarkerType.SCRIPT_MATCH] == EDLColor.Green
        assert MARKER_COLOR_MAP[MarkerType.IMAGEN] == EDLColor.Green

    def test_magenta_markers(self):
        """Req 13.3: Magenta para AI_PROMPT."""
        assert MARKER_COLOR_MAP[MarkerType.AI_PROMPT] == EDLColor.Magenta

    def test_cyan_markers(self):
        """Req 13.3: Cyan para ENTRADA."""
        assert MARKER_COLOR_MAP[MarkerType.ENTRADA] == EDLColor.Cyan

    def test_yellow_markers(self):
        """Req 13.3: Yellow para SALIDA."""
        assert MARKER_COLOR_MAP[MarkerType.SALIDA] == EDLColor.Yellow

    def test_map_has_11_entries(self):
        """El mapa tiene exactamente 11 entradas (10 originales + PANIC)."""
        assert len(MARKER_COLOR_MAP) == 11

    def test_all_map_values_are_edl_colors(self):
        for marker, color in MARKER_COLOR_MAP.items():
            assert isinstance(marker, MarkerType)
            assert isinstance(color, EDLColor)
