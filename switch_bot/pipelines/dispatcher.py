"""QuadDispatcher — Despacho simultáneo a los 4 pipelines.

Implementa el despacho paralelo del EnrichedPayload a todos los
pipelines registrados con tolerancia a fallas individuales.

Requisitos: 16.2, 16.3, 16.4
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from switch_bot.models.payload import EnrichedPayload
from switch_bot.pipelines.base import Pipeline


@dataclass(frozen=True)
class DispatchResult:
    """Resultado del despacho paralelo a los pipelines.

    Attributes:
        total: Número total de pipelines despachados.
        successes: Cantidad de pipelines que completaron sin error.
        failures: Cantidad de pipelines que fallaron.
        errors: Lista de excepciones capturadas (una por pipeline fallido).
    """

    total: int
    successes: int
    failures: int
    errors: list[Exception] = field(default_factory=list)


class QuadDispatcher:
    """Despacho simultáneo a los 4 pipelines con tolerancia a fallas.

    Envía el EnrichedPayload a todos los pipelines en paralelo usando
    asyncio.gather con return_exceptions=True, garantizando que la falla
    de un pipeline individual no bloquee la ejecución de los demás.
    """

    def __init__(self, pipelines: list[Pipeline]) -> None:
        """Inicializa el dispatcher con la lista de pipelines.

        Args:
            pipelines: Lista de pipelines a despachar (típicamente 4).
        """
        self._pipelines = pipelines

    @property
    def pipelines(self) -> list[Pipeline]:
        """Retorna la lista de pipelines registrados."""
        return self._pipelines

    async def dispatch(self, payload: EnrichedPayload) -> DispatchResult:
        """Despacha el payload a todos los pipelines en paralelo.

        La falla de un pipeline no bloquea los demás. Todas las
        excepciones se capturan y reportan en el DispatchResult.

        Args:
            payload: Payload enriquecido unificado.

        Returns:
            DispatchResult con conteo de éxitos, fallas y errores.
        """
        tasks = [pipeline.execute(payload) for pipeline in self._pipelines]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors: list[Exception] = []
        successes = 0

        for result in results:
            if isinstance(result, BaseException):
                errors.append(
                    result if isinstance(result, Exception) else RuntimeError(str(result))
                )
            else:
                successes += 1

        return DispatchResult(
            total=len(self._pipelines),
            successes=successes,
            failures=len(errors),
            errors=errors,
        )
