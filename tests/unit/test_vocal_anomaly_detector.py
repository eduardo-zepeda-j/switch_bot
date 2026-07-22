"""Tests unitarios para VocalAnomalyDetector.

Verifica detección de anomalías vocales: tos, errores de dicción,
confusión y repetición. Valida que anomalías bypass histéresis.

Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.engines.vocal_anomaly_detector import (
    AudioFeatures,
    VocalAnomaly,
    VocalAnomalyDetector,
)
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def script_doc() -> ScriptDocument:
    """Documento de guión de prueba con bloques de diálogo."""
    return ScriptDocument(
        title="Programa Test",
        blocks=[
            ScriptBlock(
                index=0,
                character="PRESENTADOR",
                text="Bienvenidos al programa de hoy",
            ),
            ScriptBlock(
                index=1,
                character="PRESENTADOR",
                text="Vamos a hablar sobre tecnología",
            ),
            ScriptBlock(
                index=2,
                character="INVITADO",
                text="Muchas gracias por la invitación",
            ),
        ],
        character_camera_map={"PRESENTADOR": 1, "INVITADO": 2},
    )


@pytest.fixture
def mock_backend() -> MagicMock:
    """Backend de IA simulado."""
    backend = MagicMock()
    backend.compute_similarity = AsyncMock(return_value=0.8)
    backend.analyze_context = AsyncMock(return_value="análisis mock")
    type(backend).backend_type = PropertyMock(return_value="mock")
    type(backend).is_connected = PropertyMock(return_value=True)
    return backend


@pytest.fixture
def mock_enricher(mock_backend: MagicMock, script_doc: ScriptDocument) -> MagicMock:
    """IAEnricher simulado con backend mock."""
    enricher = MagicMock(spec=IAEnricher)
    type(enricher).active_backend = PropertyMock(return_value=mock_backend)
    enricher._backend = mock_backend
    enricher._script_doc = script_doc
    return enricher


@pytest.fixture
def detector(
    mock_enricher: MagicMock, script_doc: ScriptDocument
) -> VocalAnomalyDetector:
    """VocalAnomalyDetector con mocks para testing."""
    return VocalAnomalyDetector(enricher=mock_enricher, script_context=script_doc)


@pytest.fixture
def normal_audio() -> AudioFeatures:
    """Características de audio normales (sin indicadores de tos)."""
    return AudioFeatures(
        energy_level=0.4,
        has_silence_gap=False,
        duration_ms=2000,
    )


@pytest.fixture
def cough_audio() -> AudioFeatures:
    """Características de audio con patrón de tos (silencio + energía alta)."""
    return AudioFeatures(
        energy_level=0.85,
        has_silence_gap=True,
        duration_ms=1500,
    )


# ---------------------------------------------------------------------------
# Tests: Detección de Tos (Req 7.1)
# ---------------------------------------------------------------------------


class TestCoughDetection:
    """Req 7.1: Detecta pausa prolongada con tos → marcador TOS Red."""

    @pytest.mark.asyncio
    async def test_cough_text_pattern_detected(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Transcripción con indicador de tos genera anomalía TOS."""
        anomalies = await detector.analyze_segment("[tos]", normal_audio)

        tos_anomalies = [a for a in anomalies if a.anomaly_type == MarkerType.TOS]
        assert len(tos_anomalies) == 1
        assert tos_anomalies[0].color == EDLColor.Red
        assert tos_anomalies[0].confidence >= 0.7

    @pytest.mark.asyncio
    async def test_cough_audio_pattern_detected(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Silencio prolongado + burst de energía genera anomalía TOS."""
        anomalies = await detector.analyze_segment("", cough_audio)

        tos_anomalies = [a for a in anomalies if a.anomaly_type == MarkerType.TOS]
        assert len(tos_anomalies) == 1
        assert tos_anomalies[0].anomaly_type == MarkerType.TOS
        assert tos_anomalies[0].color == EDLColor.Red

    @pytest.mark.asyncio
    async def test_cough_both_text_and_audio(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Doble indicador (texto + audio) da mayor confianza."""
        anomalies = await detector.analyze_segment("[tos]", cough_audio)

        tos_anomalies = [a for a in anomalies if a.anomaly_type == MarkerType.TOS]
        assert len(tos_anomalies) == 1
        assert tos_anomalies[0].confidence >= 0.9

    @pytest.mark.asyncio
    async def test_no_cough_when_normal(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Audio normal sin patrones de tos no genera anomalía TOS."""
        # Set high similarity to avoid confusion/diction errors too
        detector._enricher.active_backend.compute_similarity.return_value = 0.9

        anomalies = await detector.analyze_segment(
            "Bienvenidos al programa de hoy", normal_audio
        )

        tos_anomalies = [a for a in anomalies if a.anomaly_type == MarkerType.TOS]
        assert len(tos_anomalies) == 0


# ---------------------------------------------------------------------------
# Tests: Error de Dicción (Req 7.2)
# ---------------------------------------------------------------------------


class TestDictionErrorDetection:
    """Req 7.2: Detecta tartamudeo/mala pronunciación → ERROR_DICCION Red."""

    @pytest.mark.asyncio
    async def test_stutter_detected(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Tartamudeo explícito en transcripción genera ERROR_DICCION."""
        anomalies = await detector.analyze_segment(
            "pa-palabra incorrecta", normal_audio
        )

        diction = [a for a in anomalies if a.anomaly_type == MarkerType.ERROR_DICCION]
        assert len(diction) == 1
        assert diction[0].color == EDLColor.Red
        assert diction[0].confidence >= 0.7

    @pytest.mark.asyncio
    async def test_hesitation_detected(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Muletilla / hesitación genera ERROR_DICCION."""
        anomalies = await detector.analyze_segment(
            "ehm bueno entonces", normal_audio
        )

        diction = [a for a in anomalies if a.anomaly_type == MarkerType.ERROR_DICCION]
        assert len(diction) == 1

    @pytest.mark.asyncio
    async def test_backend_diction_error(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Similitud intermedia con guión (>0.3, <0.6) indica error de dicción."""
        # Simular que el backend devuelve similitud intermedia
        detector._enricher.active_backend.compute_similarity.return_value = 0.45

        anomalies = await detector.analyze_segment(
            "Bienvedos al pograma de hoi", normal_audio
        )

        diction = [a for a in anomalies if a.anomaly_type == MarkerType.ERROR_DICCION]
        assert len(diction) >= 1


# ---------------------------------------------------------------------------
# Tests: Confusión (Req 7.3)
# ---------------------------------------------------------------------------


class TestConfusionDetection:
    """Req 7.3: Detecta cambio involuntario de tema → CONFUSION Red."""

    @pytest.mark.asyncio
    async def test_off_topic_detected(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Texto completamente fuera del contexto del guión genera CONFUSION."""
        # Simular similitud muy baja con el guión
        detector._enricher.active_backend.compute_similarity.return_value = 0.1

        anomalies = await detector.analyze_segment(
            "El partido de fútbol del domingo fue increíble",
            normal_audio,
        )

        confusion = [a for a in anomalies if a.anomaly_type == MarkerType.CONFUSION]
        assert len(confusion) == 1
        assert confusion[0].color == EDLColor.Red

    @pytest.mark.asyncio
    async def test_no_confusion_when_on_topic(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Texto alineado con el guión no genera confusión."""
        # Similitud alta = no confusión
        detector._enricher.active_backend.compute_similarity.return_value = 0.85

        anomalies = await detector.analyze_segment(
            "Bienvenidos al programa de hoy", normal_audio
        )

        confusion = [a for a in anomalies if a.anomaly_type == MarkerType.CONFUSION]
        assert len(confusion) == 0

    @pytest.mark.asyncio
    async def test_short_text_no_confusion(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Textos muy cortos (<3 palabras) no se evalúan para confusión."""
        detector._enricher.active_backend.compute_similarity.return_value = 0.1

        anomalies = await detector.analyze_segment("sí claro", normal_audio)

        confusion = [a for a in anomalies if a.anomaly_type == MarkerType.CONFUSION]
        assert len(confusion) == 0


# ---------------------------------------------------------------------------
# Tests: Repetición (Req 7.4)
# ---------------------------------------------------------------------------


class TestRepetitionDetection:
    """Req 7.4: Detecta repetición de frase/bloque → REPETICION Red."""

    @pytest.mark.asyncio
    async def test_repeated_segment_detected(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Repetir un segmento previo genera REPETICION."""
        # Configurar para no detectar otros errores
        detector._enricher.active_backend.compute_similarity.return_value = 0.9

        # Primer segmento: registrado sin generar repetición
        await detector.analyze_segment(
            "Vamos a hablar sobre tecnología y futuro", normal_audio
        )

        # Segundo segmento: repetición del primero
        anomalies = await detector.analyze_segment(
            "Vamos a hablar sobre tecnología y futuro", normal_audio
        )

        repetition = [a for a in anomalies if a.anomaly_type == MarkerType.REPETICION]
        assert len(repetition) == 1
        assert repetition[0].color == EDLColor.Red
        assert repetition[0].confidence >= 0.75

    @pytest.mark.asyncio
    async def test_no_repetition_different_text(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Textos distintos no generan REPETICION."""
        detector._enricher.active_backend.compute_similarity.return_value = 0.9

        await detector.analyze_segment(
            "Bienvenidos al programa de hoy", normal_audio
        )

        anomalies = await detector.analyze_segment(
            "Ahora pasamos a otro tema completamente diferente", normal_audio
        )

        repetition = [a for a in anomalies if a.anomaly_type == MarkerType.REPETICION]
        assert len(repetition) == 0


# ---------------------------------------------------------------------------
# Tests: SourceOrigin y bypass de histéresis (Req 7.6)
# ---------------------------------------------------------------------------


class TestAnomalySourceAndHysteresis:
    """Req 7.6: Anomalías tienen SourceOrigin.ANOMALY, sin cooldown."""

    @pytest.mark.asyncio
    async def test_all_anomalies_have_anomaly_source(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Todas las anomalías generadas tienen SourceOrigin.ANOMALY."""
        anomalies = await detector.analyze_segment("[tos]", cough_audio)

        for anomaly in anomalies:
            assert anomaly.source_origin == SourceOrigin.ANOMALY

    @pytest.mark.asyncio
    async def test_all_anomalies_have_red_color(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Todas las anomalías vocales tienen color Red."""
        anomalies = await detector.analyze_segment("[tos]", cough_audio)

        for anomaly in anomalies:
            assert anomaly.color == EDLColor.Red

    @pytest.mark.asyncio
    async def test_consecutive_anomalies_no_cooldown(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Req 7.6: Múltiples anomalías consecutivas sin cooldown."""
        # Primera tos
        result1 = await detector.analyze_segment("[tos]", cough_audio)
        # Segunda tos inmediatamente
        result2 = await detector.analyze_segment("[tos]", cough_audio)

        tos1 = [a for a in result1 if a.anomaly_type == MarkerType.TOS]
        tos2 = [a for a in result2 if a.anomaly_type == MarkerType.TOS]

        # Ambas generan marcador sin restricción de cooldown
        assert len(tos1) >= 1
        assert len(tos2) >= 1

    @pytest.mark.asyncio
    async def test_multiple_anomaly_types_in_one_segment(
        self, detector: VocalAnomalyDetector, cough_audio: AudioFeatures
    ) -> None:
        """Un segmento puede generar múltiples tipos de anomalía."""
        # Transcripción con tos Y tartamudeo
        detector._enricher.active_backend.compute_similarity.return_value = 0.9

        anomalies = await detector.analyze_segment(
            "[tos] ehm entonces", cough_audio
        )

        types = {a.anomaly_type for a in anomalies}
        # Debería tener al menos TOS y ERROR_DICCION
        assert MarkerType.TOS in types
        assert MarkerType.ERROR_DICCION in types


# ---------------------------------------------------------------------------
# Tests: Integración con IAEnricher (Req 7.5)
# ---------------------------------------------------------------------------


class TestIAEnricherIntegration:
    """Req 7.5: Usa IAEnricher para comparación agnóstica al backend."""

    @pytest.mark.asyncio
    async def test_uses_backend_compute_similarity(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """El detector llama a compute_similarity del backend activo."""
        detector._enricher.active_backend.compute_similarity.return_value = 0.1

        await detector.analyze_segment(
            "Texto completamente fuera de contexto para prueba",
            normal_audio,
        )

        # Debe haber llamado a compute_similarity al menos una vez
        detector._enricher.active_backend.compute_similarity.assert_called()

    @pytest.mark.asyncio
    async def test_handles_backend_error_gracefully(
        self, detector: VocalAnomalyDetector, normal_audio: AudioFeatures
    ) -> None:
        """Si el backend falla, el detector no lanza excepción."""
        from switch_bot.ia.backend_base import BackendConnectionError

        detector._enricher.active_backend.compute_similarity.side_effect = (
            BackendConnectionError("Connection lost")
        )

        # No debe lanzar excepción
        anomalies = await detector.analyze_segment(
            "Texto para analizar con backend roto", normal_audio
        )

        # Puede o no tener anomalías locales pero no debe fallar
        assert isinstance(anomalies, list)
