"""Property-based tests para QuadDispatcher — despacho con tolerancia a fallas.

**Validates: Requirements 16.2, 16.3**

Verifica las propiedades universales del despacho:
- Property 9 (Req 16.2): El payload se despacha a TODOS los pipelines registrados.
- Property 9 (Req 16.3): La falla de pipelines individuales NO impide la ejecución
  de los demás. El invariante successes + failures == total siempre se cumple.
"""

from __future__ import annotations

import pytest
from hypothesis import given, assume
from hypothesis.strategies import composite, integers, sampled_from, text, lists, booleans

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.base import Pipeline
from switch_bot.pipelines.dispatcher import DispatchResult, QuadDispatcher


# --- Strategies ---


@composite
def valid_smpte_timecode(draw):
    """Genera instancias válidas de SMPTETimecode respetando reglas Drop Frame."""
    drop_frame = draw(booleans())
    hours = draw(integers(min_value=0, max_value=23))
    minutes = draw(integers(min_value=0, max_value=59))
    seconds = draw(integers(min_value=0, max_value=59))
    frames = draw(integers(min_value=0, max_value=29))

    # En Drop Frame, frames 0 y 1 no existen en segundo 0 de minutos no múltiplo de 10
    if drop_frame and seconds == 0 and minutes % 10 != 0:
        assume(frames >= 2)

    return SMPTETimecode(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        frames=frames,
        drop_frame=drop_frame,
    )


@composite
def valid_enriched_payload(draw):
    """Genera instancias válidas de EnrichedPayload con campos correctos."""
    personaje = draw(
        text(
            min_size=1,
            max_size=50,
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ áéíóúñÁÉÍÓÚÑ",
        )
    )
    target_cam = draw(integers(min_value=1, max_value=4))
    marker_type = draw(sampled_from(list(MarkerType)))
    note = draw(text(min_size=0, max_size=200))
    tc_in = draw(valid_smpte_timecode())
    source_origin = draw(sampled_from(list(SourceOrigin)))
    color = draw(sampled_from(list(EDLColor)))

    return EnrichedPayload(
        personaje=personaje,
        target_cam=target_cam,
        marker_type=marker_type,
        note=note,
        tc_in=tc_in,
        source_origin=source_origin,
        color=color,
    )


# --- Mock Pipelines ---


class SuccessPipeline(Pipeline):
    """Pipeline que siempre ejecuta con éxito y registra el payload recibido."""

    def __init__(self) -> None:
        self.executed = False
        self.received_payload: EnrichedPayload | None = None

    async def execute(self, payload: EnrichedPayload) -> None:
        self.executed = True
        self.received_payload = payload

    def is_healthy(self) -> bool:
        return True


class FailingPipeline(Pipeline):
    """Pipeline que siempre falla con un RuntimeError."""

    def __init__(self, error_msg: str = "Pipeline error") -> None:
        self._error_msg = error_msg
        self.executed = False

    async def execute(self, payload: EnrichedPayload) -> None:
        self.executed = True
        raise RuntimeError(self._error_msg)

    def is_healthy(self) -> bool:
        return False


# --- Property Tests ---


@pytest.mark.asyncio
@given(payload=valid_enriched_payload(), num_pipelines=integers(min_value=1, max_value=10))
async def test_payload_dispatched_to_all_pipelines(
    payload: EnrichedPayload, num_pipelines: int
):
    """Property 9 (Req 16.2): El payload se despacha a TODOS los pipelines.

    Para cualquier EnrichedPayload válido y cualquier número de pipelines (1-10),
    el QuadDispatcher despacha el payload a todos. Cada pipeline recibe exactamente
    el mismo payload.

    **Validates: Requirements 16.2**
    """
    pipelines = [SuccessPipeline() for _ in range(num_pipelines)]
    dispatcher = QuadDispatcher(pipelines)

    result = await dispatcher.dispatch(payload)

    # Todos los pipelines fueron despachados
    assert result.total == num_pipelines
    assert result.successes == num_pipelines
    assert result.failures == 0
    assert result.errors == []

    # Cada pipeline recibió exactamente el mismo payload
    for p in pipelines:
        assert p.executed, "Pipeline no fue ejecutado"
        assert p.received_payload == payload, (
            f"Pipeline recibió payload distinto: {p.received_payload} != {payload}"
        )


@pytest.mark.asyncio
@given(
    payload=valid_enriched_payload(),
    num_success=integers(min_value=0, max_value=10),
    num_failing=integers(min_value=0, max_value=10),
)
async def test_fault_tolerance_failing_pipelines_do_not_block_others(
    payload: EnrichedPayload, num_success: int, num_failing: int
):
    """Property 9 (Req 16.3): La falla de pipelines no bloquea los demás.

    Para cualquier combinación de N pipelines exitosos y M pipelines fallidos,
    la falla de cualquier pipeline individual NO impide que los otros reciban
    y ejecuten el payload correctamente.

    Invariante: result.successes + result.failures == result.total

    **Validates: Requirements 16.3**
    """
    # Asegurar al menos 1 pipeline total
    assume(num_success + num_failing >= 1)

    success_pipes = [SuccessPipeline() for _ in range(num_success)]
    failing_pipes = [FailingPipeline(f"error_{i}") for i in range(num_failing)]
    all_pipelines: list[Pipeline] = [*success_pipes, *failing_pipes]

    dispatcher = QuadDispatcher(all_pipelines)
    result = await dispatcher.dispatch(payload)

    # Todos los pipelines fueron intentados
    assert result.total == num_success + num_failing

    # Conteo correcto de éxitos y fallas
    assert result.successes == num_success, (
        f"Esperado {num_success} éxitos, obtenido {result.successes}"
    )
    assert result.failures == num_failing, (
        f"Esperado {num_failing} fallas, obtenido {result.failures}"
    )

    # Errores capturados correctamente
    assert len(result.errors) == num_failing, (
        f"Esperado {num_failing} errores, capturados {len(result.errors)}"
    )

    # Invariante fundamental: successes + failures == total
    assert result.successes + result.failures == result.total

    # Los pipelines exitosos SIEMPRE se ejecutaron correctamente
    # independientemente de las fallas de los otros
    for p in success_pipes:
        assert p.executed, "Pipeline exitoso no fue ejecutado"
        assert p.received_payload == payload, (
            "Pipeline exitoso recibió payload distinto"
        )

    # Los pipelines fallidos también fueron ejecutados (intentados)
    for p in failing_pipes:
        assert p.executed, "Pipeline fallido no fue intentado"
