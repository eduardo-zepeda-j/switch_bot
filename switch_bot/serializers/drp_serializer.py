"""Serialización y parsing de archivos DRP (DaVinci Resolve Project) en formato JSON Lines.

El formato DRP consiste en:
- Primera línea: configuración completa del proyecto como objeto JSON
- Líneas subsiguientes: eventos de conmutación, cada uno como objeto JSON independiente

La estrategia de round-trip almacena los datos como diccionarios crudos para preservar
todos los campos (incluso desconocidos) durante serialización/parsing.

Requisitos: 12.1, 12.2, 12.3, 12.4, 12.5, 14.1, 14.2, 14.3, 14.4
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DRPSource:
    """Representa una fuente de video/color/media en el proyecto DRP.

    Almacena los datos crudos del JSON para garantizar round-trip perfecto.
    """

    data: dict[str, Any]

    @property
    def name(self) -> str:
        return self.data.get("name", "")

    @property
    def type(self) -> str:
        return self.data.get("type", "")

    @property
    def index(self) -> int:
        return self.data.get("_index_", 0)


@dataclass(frozen=True)
class DRPMixEffectBlock:
    """Representa un Mix Effect Block en el proyecto DRP.

    Almacena los datos crudos del JSON para garantizar round-trip perfecto.
    """

    data: dict[str, Any]

    @property
    def source(self) -> int:
        return self.data.get("source", 0)

    @property
    def index(self) -> int:
        return self.data.get("_index_", 0)

    @property
    def on_air(self) -> bool | None:
        return self.data.get("onAir")


@dataclass(frozen=True)
class DRPProjectConfig:
    """Configuración completa del proyecto DRP.

    Primera línea del archivo .drp. Contiene toda la información de setup
    del proyecto: versión, timecode master, modo de video, fuentes,
    mix effect blocks, downstream keys y recording ID.
    """

    data: dict[str, Any]

    @property
    def version(self) -> int:
        return self.data.get("version", 1)

    @property
    def master_timecode(self) -> str:
        return self.data.get("masterTimecode", "00:00:00;00")

    @property
    def video_mode(self) -> str:
        return self.data.get("videoMode", "1080p29.97")

    @property
    def sources(self) -> list[DRPSource]:
        return [DRPSource(data=s) for s in self.data.get("sources", [])]

    @property
    def mix_effect_blocks(self) -> list[DRPMixEffectBlock]:
        return [DRPMixEffectBlock(data=m) for m in self.data.get("mixEffectBlocks", [])]

    @property
    def downstream_keys(self) -> list[dict[str, Any]]:
        return self.data.get("downstreamKeys", [])

    @property
    def recording_id(self) -> str:
        return self.data.get("recordingId", "")


@dataclass(frozen=True)
class DRPSwitchEvent:
    """Evento de conmutación en el archivo DRP.

    Cada evento ocupa una línea JSON con masterTimecode
    y los mixEffectBlocks afectados.
    """

    data: dict[str, Any]

    @property
    def master_timecode(self) -> str:
        return self.data.get("masterTimecode", "00:00:00;00")

    @property
    def mix_effect_blocks(self) -> list[DRPMixEffectBlock]:
        return [DRPMixEffectBlock(data=m) for m in self.data.get("mixEffectBlocks", [])]


@dataclass
class DRPDocument:
    """Documento DRP completo con serialización JSON Lines.

    Encapsula la configuración del proyecto y la secuencia de eventos
    de conmutación. Garantiza round-trip fiel al preservar los datos
    crudos de cada línea JSON.
    """

    config: DRPProjectConfig
    events: list[DRPSwitchEvent] = field(default_factory=list)

    def serialize(self) -> str:
        """Serializa el documento DRP a formato JSON Lines.

        Primera línea = configuración JSON del proyecto.
        Líneas siguientes = eventos JSON de conmutación.

        Returns:
            String con el contenido completo del archivo .drp
        """
        lines: list[str] = []

        # Primera línea: configuración del proyecto
        lines.append(json.dumps(self.config.data, ensure_ascii=False, separators=(",", ":")))

        # Líneas siguientes: eventos de conmutación
        for event in self.events:
            lines.append(json.dumps(event.data, ensure_ascii=False, separators=(",", ":")))

        # El archivo termina con newline final
        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, content: str) -> DRPDocument:
        """Parsea un archivo DRP desde su contenido texto (JSON Lines).

        La primera línea se interpreta como configuración del proyecto.
        Las líneas restantes son eventos de conmutación.

        Args:
            content: Contenido completo del archivo .drp

        Returns:
            DRPDocument reconstruido desde el contenido.

        Raises:
            ValueError: Si el contenido está vacío o no es JSON válido.
        """
        lines = [line for line in content.split("\n") if line.strip()]

        if not lines:
            raise ValueError("El archivo DRP está vacío")

        # Primera línea: configuración del proyecto
        config_data = json.loads(lines[0])
        config = DRPProjectConfig(data=config_data)

        # Líneas restantes: eventos de conmutación
        events: list[DRPSwitchEvent] = []
        for line in lines[1:]:
            event_data = json.loads(line)
            events.append(DRPSwitchEvent(data=event_data))

        return cls(config=config, events=events)

    def add_switch_event(self, timecode: str, source: int, me_index: int = 0) -> None:
        """Agrega un nuevo evento de conmutación al documento.

        Args:
            timecode: Timecode SMPTE del evento (e.g. "10:43:16;26")
            source: Índice de la fuente destino
            me_index: Índice del Mix Effect Block (default 0)
        """
        event_data: dict[str, Any] = {
            "masterTimecode": timecode,
            "mixEffectBlocks": [{"source": source, "_index_": me_index}],
        }
        self.events.append(DRPSwitchEvent(data=event_data))
