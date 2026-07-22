"""Unit tests para EnrichmentResult."""

import pytest

from switch_bot.ia.enrichment_result import EnrichmentResult, DEFAULT_DEVIATION_THRESHOLD
from switch_bot.models.enums import EDLColor, MarkerType


class TestEnrichmentResultCreation:
    """Tests para creación de EnrichmentResult."""

    def test_create_match_result(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.85,
            is_deviation=False,
            detected_text="hola mundo",
            expected_text="hola mundo",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        assert result.similarity_score == 0.85
        assert result.is_deviation is False
        assert result.detected_text == "hola mundo"
        assert result.expected_text == "hola mundo"
        assert result.marker_type == MarkerType.SCRIPT_MATCH
        assert result.color == EDLColor.Green
        assert result.metadata is None

    def test_create_deviation_result(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.3,
            is_deviation=True,
            detected_text="texto incorrecto",
            expected_text="texto esperado",
            marker_type=MarkerType.SCRIPT_DEVIATION,
            color=EDLColor.Magenta,
        )
        assert result.similarity_score == 0.3
        assert result.is_deviation is True
        assert result.marker_type == MarkerType.SCRIPT_DEVIATION
        assert result.color == EDLColor.Magenta

    def test_create_with_metadata(self) -> None:
        meta = {"backend": "bedrock", "model": "titan-embed-v2"}
        result = EnrichmentResult(
            similarity_score=0.9,
            is_deviation=False,
            detected_text="texto",
            expected_text="texto",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
            metadata=meta,
        )
        assert result.metadata == {"backend": "bedrock", "model": "titan-embed-v2"}

    def test_create_with_none_marker_and_color(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.5,
            is_deviation=False,
            detected_text="algo",
            expected_text="algo",
            marker_type=None,
            color=None,
        )
        assert result.marker_type is None
        assert result.color is None


class TestEnrichmentResultValidation:
    """Tests para validación de similarity_score."""

    def test_score_zero_is_valid(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.0,
            is_deviation=True,
            detected_text="",
            expected_text="texto",
            marker_type=MarkerType.SCRIPT_DEVIATION,
            color=EDLColor.Magenta,
        )
        assert result.similarity_score == 0.0

    def test_score_one_is_valid(self) -> None:
        result = EnrichmentResult(
            similarity_score=1.0,
            is_deviation=False,
            detected_text="perfecto",
            expected_text="perfecto",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        assert result.similarity_score == 1.0

    def test_score_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="similarity_score debe estar en"):
            EnrichmentResult(
                similarity_score=-0.1,
                is_deviation=True,
                detected_text="x",
                expected_text="y",
                marker_type=None,
                color=None,
            )

    def test_score_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="similarity_score debe estar en"):
            EnrichmentResult(
                similarity_score=1.1,
                is_deviation=False,
                detected_text="x",
                expected_text="y",
                marker_type=None,
                color=None,
            )

    def test_score_non_numeric_raises(self) -> None:
        with pytest.raises(TypeError, match="similarity_score debe ser numérico"):
            EnrichmentResult(
                similarity_score="alto",  # type: ignore[arg-type]
                is_deviation=False,
                detected_text="x",
                expected_text="y",
                marker_type=None,
                color=None,
            )

    def test_integer_score_is_accepted(self) -> None:
        result = EnrichmentResult(
            similarity_score=1,
            is_deviation=False,
            detected_text="x",
            expected_text="x",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        assert result.similarity_score == 1


class TestEnrichmentResultImmutability:
    """Tests para verificar que el dataclass es inmutable (frozen)."""

    def test_cannot_modify_score(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.8,
            is_deviation=False,
            detected_text="a",
            expected_text="a",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        with pytest.raises(AttributeError):
            result.similarity_score = 0.5  # type: ignore[misc]

    def test_cannot_modify_is_deviation(self) -> None:
        result = EnrichmentResult(
            similarity_score=0.8,
            is_deviation=False,
            detected_text="a",
            expected_text="a",
            marker_type=MarkerType.SCRIPT_MATCH,
            color=EDLColor.Green,
        )
        with pytest.raises(AttributeError):
            result.is_deviation = True  # type: ignore[misc]


class TestEnrichmentResultFactoryMethods:
    """Tests para factory methods from_match y from_deviation."""

    def test_from_match_creates_correct_result(self) -> None:
        result = EnrichmentResult.from_match(
            similarity_score=0.95,
            detected_text="hola",
            expected_text="hola",
        )
        assert result.is_deviation is False
        assert result.marker_type == MarkerType.SCRIPT_MATCH
        assert result.color == EDLColor.Green
        assert result.similarity_score == 0.95
        assert result.metadata is None

    def test_from_match_with_metadata(self) -> None:
        meta = {"latency_ms": 120}
        result = EnrichmentResult.from_match(
            similarity_score=0.8,
            detected_text="texto",
            expected_text="texto",
            metadata=meta,
        )
        assert result.metadata == {"latency_ms": 120}

    def test_from_deviation_creates_correct_result(self) -> None:
        result = EnrichmentResult.from_deviation(
            similarity_score=0.4,
            detected_text="algo diferente",
            expected_text="texto original",
        )
        assert result.is_deviation is True
        assert result.marker_type == MarkerType.SCRIPT_DEVIATION
        assert result.color == EDLColor.Magenta
        assert result.similarity_score == 0.4
        assert result.metadata is None

    def test_from_deviation_with_metadata(self) -> None:
        meta = {"backend": "local", "model": "nomic-embed"}
        result = EnrichmentResult.from_deviation(
            similarity_score=0.2,
            detected_text="x",
            expected_text="y",
            metadata=meta,
        )
        assert result.metadata == {"backend": "local", "model": "nomic-embed"}

    def test_from_match_validates_score(self) -> None:
        with pytest.raises(ValueError):
            EnrichmentResult.from_match(
                similarity_score=1.5,
                detected_text="a",
                expected_text="a",
            )

    def test_from_deviation_validates_score(self) -> None:
        with pytest.raises(ValueError):
            EnrichmentResult.from_deviation(
                similarity_score=-0.3,
                detected_text="a",
                expected_text="b",
            )


class TestEnrichmentResultEquality:
    """Tests para igualdad entre instancias."""

    def test_equal_instances(self) -> None:
        r1 = EnrichmentResult.from_match(0.9, "a", "a")
        r2 = EnrichmentResult.from_match(0.9, "a", "a")
        assert r1 == r2

    def test_different_score_not_equal(self) -> None:
        r1 = EnrichmentResult.from_match(0.9, "a", "a")
        r2 = EnrichmentResult.from_match(0.8, "a", "a")
        assert r1 != r2


class TestEnrichmentResultImport:
    """Tests para verificar exportación desde módulo ia."""

    def test_import_from_ia_module(self) -> None:
        from switch_bot.ia import EnrichmentResult as Imported
        assert Imported is EnrichmentResult


class TestDefaultDeviationThreshold:
    """Tests para la constante DEFAULT_DEVIATION_THRESHOLD."""

    def test_threshold_value(self) -> None:
        assert DEFAULT_DEVIATION_THRESHOLD == 0.7
