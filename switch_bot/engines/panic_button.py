"""Panic Button — Override manual de emergencia.

Implementa el mecanismo de pausa inmediata de automatización
e inyección de banderas de emergencia en el EDL. Diseñado para
garantizar respuesta sub-frame (< 33.33 ms a 30 fps).

Requisitos: 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

import threading

from switch_bot.models.enums import EDLColor, MarkerType
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.serializers.edl_serializer import EDLDocument


class PanicButton:
    """Override manual de emergencia para pausar automatización.

    Cuando se activa, pausa todas las conmutaciones automáticas de cámara
    de forma inmediata y registra una bandera de emergencia en el EDL con
    el SMPTE_TC del momento de activación.

    Al desactivarse, restaura la operación automática desde el estado actual.

    Garantiza respuesta < 1 frame time (33.33 ms) usando una flag atómica
    con threading.Event para visibilidad cross-thread inmediata.

    Attributes:
        edl_document: Documento EDL donde se registran banderas de emergencia.
    """

    def __init__(self, edl_document: EDLDocument | None = None) -> None:
        """Inicializa el PanicButton.

        Args:
            edl_document: Documento EDL opcional donde registrar banderas
                         de emergencia. Si es None, la activación solo pausa
                         la automatización sin registrar en EDL.
        """
        self._edl_document = edl_document
        self._active = threading.Event()
        self._activation_tc: SMPTETimecode | None = None
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        """True si el Panic Button está activado y la automatización pausada.

        Esta propiedad es thread-safe y tiene respuesta sub-frame.
        """
        return self._active.is_set()

    @property
    def activation_timecode(self) -> SMPTETimecode | None:
        """Timecode SMPTE del momento de activación, o None si inactivo.

        Returns:
            El timecode de la última activación, o None si nunca se ha activado
            o si se desactivó sin nueva activación.
        """
        return self._activation_tc

    def activate(self, tc: SMPTETimecode) -> None:
        """Pausa toda automatización e inyecta bandera de emergencia.

        Operación atómica diseñada para completarse en < 33.33 ms:
        1. Establece la flag de panic (inmediato, cross-thread visible)
        2. Almacena el timecode de activación
        3. Registra marcador PANIC en el EDL con el SMPTE_TC

        Args:
            tc: Timecode SMPTE del momento de activación física.
        """
        # Set de la flag es O(1) y thread-safe
        self._active.set()
        self._activation_tc = tc

        # Registrar bandera de emergencia en el EDL
        if self._edl_document is not None:
            self._edl_document.add_event(
                tc_in=tc,
                color=EDLColor.Red,
                marker_type=MarkerType.PANIC,
            )

    def deactivate(self) -> None:
        """Restaura la operación automática desde el estado actual.

        Limpia la flag de panic, permitiendo que el Motor de Decisión
        y el Filtro de Histéresis reanuden su operación normal.
        El timecode de activación se mantiene para referencia histórica.
        """
        self._active.clear()
