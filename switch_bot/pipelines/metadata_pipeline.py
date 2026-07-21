"""Pipeline Metadata — Log append-only .jsonl y compilación .drp en tiempo real.

Escribe cada evento como una línea JSON en un archivo .jsonl append-only
e integra DRPDocument para mantener el archivo .drp actualizado en tiempo
real. Usa escritura atómica con flush para garantizar consistencia ante crashes.

Requisitos: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from switch_bot.models.config import SystemConfig
from switch_bot.models.payload import EnrichedPayload
from switch_bot.pipelines.base import Pipeline
from switch_bot.serializers.drp_serializer import (
    DRPDocument,
    DRPProjectConfig,
)

logger = logging.getLogger(__name__)


class MetadataPipeline(Pipeline):
    """Escritura de log append-only (.jsonl) y compilación .drp en tiempo real.

    Mantiene dos archivos de salida:
    - Un archivo .jsonl con un evento JSON por línea (append-only).
    - Un archivo .drp (JSON Lines) con la configuración del proyecto en la
      primera línea y eventos de conmutación en líneas subsiguientes.

    Ambos archivos se escriben con flush atómico para garantizar que el
    contenido persista incluso ante crashes del sistema.

    Attributes:
        output_dir: Directorio de salida para los archivos generados.
        config: Configuración global del sistema.
    """

    def __init__(self, output_dir: Path, config: SystemConfig) -> None:
        """Inicializa el pipeline de metadata.

        Args:
            output_dir: Directorio donde se crean los archivos .jsonl y .drp.
            config: Configuración global del sistema.
        """
        self._output_dir = output_dir
        self._config = config
        self._healthy: bool = False
        self._jsonl_path: Path | None = None
        self._drp_path: Path | None = None
        self._jsonl_file: TextIO | None = None
        self._drp_file: TextIO | None = None
        self._drp_doc: DRPDocument | None = None
        self._event_count: int = 0

    def start(self, session_name: str | None = None) -> None:
        """Inicia el pipeline creando los archivos de salida.

        Crea el directorio de salida si no existe, genera nombres de archivo
        basados en el timestamp de inicio de sesión, escribe la cabecera
        del DRP y marca el pipeline como healthy.

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

        self._jsonl_path = self._output_dir / f"{session_name}.jsonl"
        self._drp_path = self._output_dir / f"{session_name}.drp"

        # Open files in append mode
        self._jsonl_file = open(self._jsonl_path, "a", encoding="utf-8")  # noqa: SIM115

        # Initialize DRP document with project config
        self._drp_doc = self._create_drp_document()

        # Write DRP header (project config) as first line
        self._drp_file = open(self._drp_path, "a", encoding="utf-8")  # noqa: SIM115
        header_line = json.dumps(
            self._drp_doc.config.data, ensure_ascii=False, separators=(",", ":")
        )
        self._drp_file.write(header_line + "\n")
        self._drp_file.flush()
        os.fsync(self._drp_file.fileno())

        self._event_count = 0
        self._healthy = True
        logger.info(
            "MetadataPipeline started: jsonl=%s, drp=%s",
            self._jsonl_path,
            self._drp_path,
        )

    def stop(self) -> None:
        """Detiene el pipeline y cierra los archivos de forma segura."""
        if self._jsonl_file is not None:
            try:
                self._jsonl_file.flush()
                os.fsync(self._jsonl_file.fileno())
                self._jsonl_file.close()
            except Exception:
                logger.exception("Error closing JSONL file")
            self._jsonl_file = None

        if self._drp_file is not None:
            try:
                self._drp_file.flush()
                os.fsync(self._drp_file.fileno())
                self._drp_file.close()
            except Exception:
                logger.exception("Error closing DRP file")
            self._drp_file = None

        self._healthy = False
        logger.info("MetadataPipeline stopped")

    async def execute(self, payload: EnrichedPayload) -> None:
        """Escribe el evento en .jsonl y actualiza el .drp.

        Cada invocación:
        1. Serializa el payload como JSON y lo escribe como nueva línea
           en el archivo .jsonl (append-only).
        2. Agrega un evento de conmutación al DRPDocument y lo escribe
           como nueva línea en el archivo .drp.
        3. Realiza flush + fsync para persistencia ante crashes.

        Las escrituras de disco (write + flush + fsync) se delegan a un
        thread del pool via asyncio.to_thread() para no bloquear el event
        loop y permitir que los demás pipelines se ejecuten sin latencia.

        Args:
            payload: Payload enriquecido unificado.

        Raises:
            RuntimeError: Si el pipeline no ha sido iniciado (start).
        """
        if not self._healthy or self._jsonl_file is None or self._drp_file is None:
            raise RuntimeError(
                "MetadataPipeline not started. Call start() before execute()."
            )

        self._event_count += 1
        timecode_str = payload.tc_in.to_string()

        # 1. Write JSONL event (Req 12.1)
        jsonl_event = self._payload_to_jsonl(payload)

        # 2. Prepare DRP event data (in-memory, fast)
        assert self._drp_doc is not None
        self._drp_doc.add_switch_event(timecode=timecode_str, source=payload.target_cam)
        last_event = self._drp_doc.events[-1]
        drp_event_line = json.dumps(
            last_event.data, ensure_ascii=False, separators=(",", ":")
        )

        # 3. Delegate disk I/O to thread pool (non-blocking)
        await asyncio.to_thread(self._write_to_disk, jsonl_event, drp_event_line)

        logger.debug(
            "MetadataPipeline event #%d: personaje=%s, cam=%d, tc=%s",
            self._event_count,
            payload.personaje,
            payload.target_cam,
            timecode_str,
        )

    def _payload_to_jsonl(self, payload: EnrichedPayload) -> dict[str, Any]:
        """Convierte un EnrichedPayload a diccionario para serialización JSONL.

        El evento incluye: ID de personaje, timecode SMPTE, nota asociada,
        tipo de marcador, origen y color.

        Args:
            payload: Payload enriquecido.

        Returns:
            Diccionario listo para serializar como JSON.
        """
        return {
            "event_number": self._event_count,
            "personaje": payload.personaje,
            "target_cam": payload.target_cam,
            "timecode": payload.tc_in.to_string(),
            "marker_type": payload.marker_type.value,
            "source_origin": payload.source_origin.value,
            "color": payload.color.value,
            "note": payload.note,
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        }

    def _write_to_disk(self, jsonl_event: dict[str, Any], drp_event_line: str) -> None:
        """Escribe ambos eventos (JSONL y DRP) a disco de forma atómica.

        Este método se ejecuta en un thread del pool (via asyncio.to_thread)
        para no bloquear el event loop. Realiza flush + fsync para garantizar
        persistencia ante crashes.

        Args:
            jsonl_event: Diccionario del evento JSONL a escribir.
            drp_event_line: Línea JSON pre-serializada del evento DRP.
        """
        assert self._jsonl_file is not None
        assert self._drp_file is not None

        # Write JSONL event
        line = json.dumps(jsonl_event, ensure_ascii=False, separators=(",", ":"))
        self._jsonl_file.write(line + "\n")
        self._jsonl_file.flush()
        os.fsync(self._jsonl_file.fileno())

        # Write DRP event
        self._drp_file.write(drp_event_line + "\n")
        self._drp_file.flush()
        os.fsync(self._drp_file.fileno())

    def _create_drp_document(self) -> DRPDocument:
        """Crea un DRPDocument con la configuración del proyecto.

        Genera la configuración inicial basada en SystemConfig:
        versión, masterTimecode, videoMode, sources estándar,
        mixEffectBlocks, downstreamKeys y recordingId.

        Returns:
            DRPDocument con config inicializada y sin eventos.
        """
        # Build standard source list (Req 12.2)
        sources = [
            {"name": "Black", "type": "black", "_index_": 0},
            {"name": "Camera 1", "type": "camera", "_index_": 1},
            {"name": "Camera 2", "type": "camera", "_index_": 2},
            {"name": "Camera 3", "type": "camera", "_index_": 3},
            {"name": "Camera 4", "type": "camera", "_index_": 4},
            {"name": "Color Bars", "type": "colorbars", "_index_": 5},
            {"name": "Color 1", "type": "color", "_index_": 6},
            {"name": "Color 2", "type": "color", "_index_": 7},
            {"name": "Media Player 1", "type": "media", "_index_": 8},
        ]

        # Initial timecode
        master_tc = "00:00:00;00" if self._config.drop_frame else "00:00:00:00"

        config_data = {
            "version": 1,
            "masterTimecode": master_tc,
            "videoMode": self._config.video_mode,
            "sources": sources,
            "mixEffectBlocks": [{"source": 1, "_index_": 0}],
            "downstreamKeys": [],
            "recordingId": datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S"),
        }

        config = DRPProjectConfig(data=config_data)
        return DRPDocument(config=config, events=[])

    def is_healthy(self) -> bool:
        """Retorna True si el pipeline está operativo.

        Returns:
            True si los archivos están abiertos y la última escritura
            fue exitosa.
        """
        return self._healthy

    @property
    def event_count(self) -> int:
        """Número de eventos escritos en esta sesión."""
        return self._event_count

    @property
    def jsonl_path(self) -> Path | None:
        """Ruta al archivo .jsonl activo."""
        return self._jsonl_path

    @property
    def drp_path(self) -> Path | None:
        """Ruta al archivo .drp activo."""
        return self._drp_path
