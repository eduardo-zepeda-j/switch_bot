"""Tests unitarios para QuadDispatcher y DispatchResult.

Valida despacho paralelo, tolerancia a fallas y conteo correcto.
"""

from __future__ import annotations

import asyncio

import pytest

from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.base import Pipeline
from switch_bot.pipelines.dispatcher import DispatchResult, QuadDispatcher


# --- Helpers ---


def _make_payload() -> EnrichedPayload:
    """Crea un payload de prueba válido."""
    return EnrichedPayload(
        personaje="Ana",
        target_cam=1,
        marker_type=MarkerType.MANUAL_NOTE,
        note="Test note",
        tc_in=SMPTETimecode(1, 0, 0, 0, drop_frame=False),
        source_origin=SourceOrigin.MANUAL,
        color=EDLColor.Red,
    )


class SuccessPipeline(Pipeline):
    """Pipeline que siempre ejecuta con éxito."""

    def __init__(self) -> None:
        self.executed = False
        self.received_payload: EnrichedPayload | None = None

    async def execute(self, payload: EnrichedPayload) -> None:
        self.executed = True
        self.received_payload = payload

    def is_healthy(self) -> bool:
        return True


class FailingPipeline(Pipeline):
    """Pipeline que siempre falla."""

    def __init__(self, error_msg: str = "Pipeline error") -> None:
        self._error_msg = error_msg

    async def execute(self, payload: EnrichedPayload) -> None:
        raise RuntimeError(self._error_msg)

    def is_healthy(self) -> bool:
        return False


class SlowPipeline(Pipeline):
    """Pipeline con retardo simulado."""

    def __init__(self, delay: float = 0.01) -> None:
        self._delay = delay
        self.executed = False

    async def execute(self, payload: EnrichedPayload) -> None:
        await asyncio.sleep(self._delay)
        self.executed = True

    def is_healthy(self) -> bool:
        return True


# --- Tests ---


class TestDispatchResult:
    """Tests para DispatchResult dataclass."""

    def test_all_success(self) -> None:
        result = DispatchResult(total=4, successes=4, failures=0, errors=[])
        assert result.total == 4
        assert result.successes == 4
        assert result.failures == 0
        assert result.errors == []

    def test_partial_failure(self) -> None:
        err = RuntimeError("fail")
        result = DispatchResult(total=4, successes=3, failures=1, errors=[err])
        assert result.total == 4
        assert result.successes == 3
        assert result.failures == 1
        assert len(result.errors) == 1

    def test_all_failure(self) -> None:
        errors = [RuntimeError(f"fail {i}") for i in range(4)]
        result = DispatchResult(total=4, successes=0, failures=4, errors=errors)
        assert result.total == 4
        assert result.successes == 0
        assert result.failures == 4
        assert len(result.errors) == 4


class TestQuadDispatcher:
    """Tests para QuadDispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_all_success(self) -> None:
        """Todos los pipelines ejecutan correctamente."""
        pipelines = [SuccessPipeline() for _ in range(4)]
        dispatcher = QuadDispatcher(pipelines)
        payload = _make_payload()

        result = await dispatcher.dispatch(payload)

        assert result.total == 4
        assert result.successes == 4
        assert result.failures == 0
        assert result.errors == []
        for p in pipelines:
            assert p.executed
            assert p.received_payload == payload

    @pytest.mark.asyncio
    async def test_dispatch_one_failure_does_not_block_others(self) -> None:
        """La falla de un pipeline no bloquea los demás."""
        success_pipes = [SuccessPipeline() for _ in range(3)]
        failing_pipe = FailingPipeline("ATEM timeout")
        pipelines: list[Pipeline] = [*success_pipes, failing_pipe]
        dispatcher = QuadDispatcher(pipelines)

        result = await dispatcher.dispatch(_make_payload())

        assert result.total == 4
        assert result.successes == 3
        assert result.failures == 1
        assert len(result.errors) == 1
        assert "ATEM timeout" in str(result.errors[0])
        for p in success_pipes:
            assert p.executed

    @pytest.mark.asyncio
    async def test_dispatch_all_failures(self) -> None:
        """Todos los pipelines fallan, resultado refleja 0 éxitos."""
        pipelines: list[Pipeline] = [
            FailingPipeline(f"error_{i}") for i in range(4)
        ]
        dispatcher = QuadDispatcher(pipelines)

        result = await dispatcher.dispatch(_make_payload())

        assert result.total == 4
        assert result.successes == 0
        assert result.failures == 4
        assert len(result.errors) == 4

    @pytest.mark.asyncio
    async def test_dispatch_parallel_execution(self) -> None:
        """Los pipelines se ejecutan en paralelo, no secuencialmente."""
        delay = 0.05
        pipelines: list[Pipeline] = [SlowPipeline(delay) for _ in range(4)]
        dispatcher = QuadDispatcher(pipelines)

        import time

        start = time.monotonic()
        result = await dispatcher.dispatch(_make_payload())
        elapsed = time.monotonic() - start

        assert result.successes == 4
        # Si fueran secuenciales tomarían ~0.2s; en paralelo < 0.15s
        assert elapsed < delay * 3, f"Ejecución demasiado lenta: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_dispatch_empty_pipelines(self) -> None:
        """Dispatcher sin pipelines retorna resultado vacío."""
        dispatcher = QuadDispatcher([])

        result = await dispatcher.dispatch(_make_payload())

        assert result.total == 0
        assert result.successes == 0
        assert result.failures == 0

    @pytest.mark.asyncio
    async def test_dispatch_mixed_slow_and_failing(self) -> None:
        """Mezcla de pipelines lentos y que fallan."""
        pipelines: list[Pipeline] = [
            SlowPipeline(0.01),
            FailingPipeline("network error"),
            SuccessPipeline(),
            SlowPipeline(0.02),
        ]
        dispatcher = QuadDispatcher(pipelines)

        result = await dispatcher.dispatch(_make_payload())

        assert result.total == 4
        assert result.successes == 3
        assert result.failures == 1

    def test_pipelines_property(self) -> None:
        """La propiedad pipelines retorna la lista correcta."""
        pipes: list[Pipeline] = [SuccessPipeline(), FailingPipeline()]
        dispatcher = QuadDispatcher(pipes)
        assert dispatcher.pipelines is pipes
