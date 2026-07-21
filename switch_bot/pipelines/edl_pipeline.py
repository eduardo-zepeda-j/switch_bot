"""Pipeline EDL — Motor CMX 3600 con escritura en tiempo real.

Genera archivos EDL válidos en formato CMX 3600 con cabecera TITLE
y FCM: NON-DROP FRAME. Clasifica cada marcador por origen (Manual,
IA/Contexto, AUTO, Anomalía) y asigna colores según la especificación.
Escribe eventos de forma incremental con flush+fsync atómico.

Requisitos: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.payload import EnrichedPayload
from switch_bot.pipelines.base import Pipeline
from switch_bot.serializers.edl_serializer import EDLDocument, EDLEvent

logger = logging.getLogger(__name__)

# Clasificación de origen para comentarios EDL (Req 13.2)
SOURCE_ORIGIN_CLASSIFICATION: dict[SourceOrigin, str] = {
    SourceOrigin.MANUAL: "Manual",
    SourceOrigin.AI: "IA/Contexto",
    SourceOrigin.AUTO: "AUTO",
    SourceOrigin.ANOMALY: "Anomalía",
}


class EDLPipeline(Pipeline):
    """Pipeline de generación de archivos EDL CMX 3600 en tiempo real.

    Mantiene un EDLDocument en memoria y escribe eventos de forma
    incremental al archivo .edl en disco. Cada evento se escribe con
    flush + fsync para garantizar persistencia ante crashes.

    La clasificación de marcadores sigue la lógica:
    - SourceOrigin.MANUAL → "Manual"
    - SourceOrigin.AI → "IA/Contexto"
    - SourceOrigin.AUTO → "AUTO"
    - SourceOrigin.ANOMALY → "Anomalía"

    Los colores se toman directamente del payload (ya resueltos por
    MARKER_COLOR_MAP en capas anteriores).

    Attributes:
        output_dir: Directorio de salida para el archivo .edl.
        config: Configuración global del sistema.
    """

    def __init__(self, output_dir: Path, config: SystemConfig) -> None:
        """Inicializa el pipeline EDL.

        Args:
            output_dir: Directorio donde se crea el archivo .edl.
            config: Configuración global del sistema.
        """
        self._output_dir = output_dir
        self._config = config
        self._healthy: bool = False
        self._edl_path: Path | None = None
        self._edl_file: TextIO | None = None
        self._edl_doc: EDLDocument | None = None
        self._event_count: int = 0

    def start(self, session_name: str | None = None) -> None:
        """Inicia el pipeline creando el archivo EDL con cabecera.

        Crea el directorio de salida si no existe, genera el nombre de
        archivo basado en el nombre de sesión, escribe la cabecera CMX 3600
        (TITLE + FCM: NON-DROP FRAME) y marca el pipeline como healthy.

        Args:
            session_name: Nombre opcional para la sesión. Si no se proporciona,
                se genera uno basado en el timestamp actual.
        """
        # Ensure output directory exists
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Generate session name
        if session_name is None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            session_name = f"session_{ts}"

        self._edl_path = self._output_dir / f"{session_name}.edl"

        # Initialize EDL document in memory (Req 13.1)
        self._edl_doc = EDLDocument(
            title=session_name,
            fcm="NON-DROP FRAME",
        )

        # Open file and write header (Req 13.1)
        self._edl_file = open(self._edl_path, "w", encoding="utf-8")  # noqa: SIM115
        self._write_header()

        self._event_count = 0
        self._healthy = True
        logger.info("EDLPipeline started: edl=%s", self._edl_path)

    def stop(self) -> None:
        """Detiene el pipeline y cierra el archivo de forma segura."""
        if self._edl_file is not None:
            try:
                self._edl_file.flush()
                os.fsync(self._edl_file.fileno())
                self._edl_file.close()
            except Exception:
                logger.exception("Error closing EDL file")
            self._edl_file = None

        self._healthy = False
        logger.info("EDLPipeline stopped")

    async def execute(self, payload: EnrichedPayload) -> None:
        """Agrega un evento EDL con clasificación de marcador y color.

        Cada invocación:
        1. Clasifica el origen del marcador (Manual, IA/Contexto, AUTO, Anomalía).
        2. Agrega el evento al EDLDocument en memoria (auto-numeración secuencial).
        3. Delega la escritura de disco (write + flush + fsync) a un thread del
           pool via asyncio.to_thread() para no bloquear el event loop.

        El evento se genera como 1 frame de duración (Req 13.4) con
        numeración secuencial de 3 dígitos (Req 13.6).

        Args:
            payload: Payload enriquecido unificado.

        Raises:
            RuntimeError: Si el pipeline no ha sido iniciado (start).
        """
        if not self._healthy or self._edl_file is None or self._edl_doc is None:
            raise RuntimeError(
                "EDLPipeline not started. Call start() before execute()."
            )

        self._event_count += 1

        # Classify marker source (Req 13.2)
        classification = self._classify_source(payload.source_origin)

        # Add event to in-memory EDL document (Req 13.4, 13.6)
        # EDLDocument.add_event() handles auto-numbering and tc_out = tc_in + 1 frame
        event = self._edl_doc.add_event(
            tc_in=payload.tc_in,
            color=payload.color,
            marker_type=payload.marker_type,
            duration=1,
        )

        # Serialize event text (fast, in-memory)
        event_text = event.to_cmx3600() + "\n\n"

        # Delegate disk I/O to thread pool (non-blocking) (Req 13.5)
        await asyncio.to_thread(self._write_event_to_disk, event_text)

        logger.debug(
            "EDLPipeline event #%03d: %s [%s] color=%s tc=%s",
            self._event_count,
            payload.marker_type.value,
            classification,
            payload.color.value,
            payload.tc_in.to_string(),
        )

    def _classify_source(self, source_origin: SourceOrigin) -> str:
        """Clasifica el origen del marcador para metadatos EDL.

        Args:
            source_origin: Origen del evento.

        Returns:
            String de clasificación: "Manual", "IA/Contexto", "AUTO", "Anomalía".
        """
        return SOURCE_ORIGIN_CLASSIFICATION.get(source_origin, "Desconocido")

    def _write_header(self) -> None:
        """Escribe la cabecera CMX 3600 (TITLE + FCM) al archivo.

        Realiza flush + fsync para escritura atómica (Req 13.5).
        """
        assert self._edl_file is not None
        assert self._edl_doc is not None

        header = f"TITLE: {self._edl_doc.title}\nFCM: {self._edl_doc.fcm}\n\n"
        self._edl_file.write(header)
        self._edl_file.flush()
        os.fsync(self._edl_file.fileno())

    def _write_event_to_disk(self, event_text: str) -> None:
        """Escribe un evento EDL pre-serializado al archivo con flush + fsync.

        Este método se ejecuta en un thread del pool (via asyncio.to_thread)
        para no bloquear el event loop durante I/O de disco.

        Args:
            event_text: Texto CMX 3600 del evento ya serializado.
        """
        assert self._edl_file is not None

        self._edl_file.write(event_text)
        self._edl_file.flush()
        os.fsync(self._edl_file.fileno())

    def is_healthy(self) -> bool:
        """Retorna True si el pipeline está operativo.

        Returns:
            True si el archivo está abierto y la última escritura fue exitosa.
        """
        return self._healthy

    @property
    def event_count(self) -> int:
        """Número de eventos escritos en esta sesión."""
        return self._event_count

    @property
    def edl_path(self) -> Path | None:
        """Ruta al archivo .edl activo."""
        return self._edl_path

    @property
    def edl_document(self) -> EDLDocument | None:
        """Referencia al documento EDL en memoria."""
        return self._edl_doc
