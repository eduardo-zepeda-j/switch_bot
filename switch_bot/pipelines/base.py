"""Interfaz abstracta Pipeline para ejecución cuádruple.

Define el contrato que todo pipeline (ATEM, OBS, Metadata, EDL)
debe cumplir para integrarse con el QuadDispatcher.

Requisitos: 16.2, 16.3
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from switch_bot.models.payload import EnrichedPayload


class Pipeline(ABC):
    """Interfaz abstracta para pipelines de ejecución.

    Cada pipeline recibe un EnrichedPayload y ejecuta su lógica
    específica (conmutar ATEM, cambiar escena OBS, escribir metadata,
    generar EDL).
    """

    @abstractmethod
    async def execute(self, payload: EnrichedPayload) -> None:
        """Ejecuta la acción del pipeline con el payload dado.

        Args:
            payload: Payload enriquecido unificado.

        Raises:
            Exception: Si la ejecución falla (no debe bloquear otros pipelines).
        """
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """Retorna True si el pipeline está operativo.

        Permite al dispatcher verificar el estado de cada pipeline
        antes o después del despacho.
        """
        ...
