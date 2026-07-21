"""Serialización y parsing de archivos EDL en formato CMX 3600.

El formato EDL CMX 3600 consiste en:
- Cabecera: TITLE y FCM (Frame Code Mode)
- Eventos: cada evento ocupa 2 líneas
  - Línea 1: NNN  001      V     C        TC_IN TC_OUT TC_IN TC_OUT
  - Línea 2:  |C:{color} |M:{tipo} |D:{duration}

Cada evento representa un marcador de 1 frame con auto-numeración secuencial.
Garantiza round-trip: parsear → serializar = original.

Requisitos: 13.1, 13.4, 13.5, 13.6, 15.1, 15.2, 15.3, 15.4
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from switch_bot.models.enums import EDLColor, MarkerType
from switch_bot.models.timecode import SMPTETimecode


# Regex para parsear la línea principal de un evento EDL CMX 3600
# Formato: NNN  001      V     C        HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF
_EVENT_LINE_PATTERN = re.compile(
    r"^(\d{3})\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"(\d{2}:\d{2}:\d{2}[;:]\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}[;:]\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}[;:]\d{2})\s+"
    r"(\d{2}:\d{2}:\d{2}[;:]\d{2})\s*$"
)

# Regex para parsear la línea de comentario de un evento
# Formato:  |C:ResolveColor{Color} |M:{TIPO} |D:{duration}
_COMMENT_LINE_PATTERN = re.compile(
    r"^\s*\|C:(\S+)\s+\|M:(\S+)\s+\|D:(\d+)\s*$"
)


@dataclass
class EDLEvent:
    """Un evento individual en el archivo EDL CMX 3600."""

    event_number: int
    reel: str = "001"
    track: str = "V"
    edit_type: str = "C"
    tc_in: SMPTETimecode = field(default_factory=lambda: SMPTETimecode(0, 0, 0, 0, False))
    tc_out: SMPTETimecode = field(default_factory=lambda: SMPTETimecode(0, 0, 0, 1, False))
    rec_in: SMPTETimecode = field(default_factory=lambda: SMPTETimecode(0, 0, 0, 0, False))
    rec_out: SMPTETimecode = field(default_factory=lambda: SMPTETimecode(0, 0, 0, 1, False))
    color: EDLColor = EDLColor.Red
    marker_type: MarkerType = MarkerType.MANUAL_NOTE
    duration: int = 1

    def to_cmx3600(self) -> str:
        """Serializa a formato CMX 3600 con comentario de color.

        Genera dos líneas:
        - Línea 1: evento con alineación de columnas fija
        - Línea 2: comentario con color, tipo de marcador y duración

        Returns:
            String con las dos líneas del evento CMX 3600.
        """
        line1 = (
            f"{self.event_number:03d}  {self.reel}      {self.track}     "
            f"{self.edit_type}        "
            f"{self.tc_in.to_string()} {self.tc_out.to_string()} "
            f"{self.rec_in.to_string()} {self.rec_out.to_string()}"
        )
        line2 = f" |C:{self.color.value} |M:{self.marker_type.value} |D:{self.duration}"
        return f"{line1}\n{line2}"

    @classmethod
    def from_cmx3600(cls, line1: str, line2: str) -> EDLEvent:
        """Parsea evento desde dos líneas CMX 3600.

        Args:
            line1: Línea principal del evento (número, reel, track, timecodes).
            line2: Línea de comentario (color, tipo, duración).

        Returns:
            EDLEvent reconstruido desde las líneas.

        Raises:
            ValueError: Si las líneas no tienen formato CMX 3600 válido.
        """
        match1 = _EVENT_LINE_PATTERN.match(line1)
        if not match1:
            raise ValueError(f"Formato de evento EDL inválido: '{line1}'")

        match2 = _COMMENT_LINE_PATTERN.match(line2)
        if not match2:
            raise ValueError(f"Formato de comentario EDL inválido: '{line2}'")

        event_number = int(match1.group(1))
        reel = match1.group(2)
        track = match1.group(3)
        edit_type = match1.group(4)
        tc_in = SMPTETimecode.from_string(match1.group(5))
        tc_out = SMPTETimecode.from_string(match1.group(6))
        rec_in = SMPTETimecode.from_string(match1.group(7))
        rec_out = SMPTETimecode.from_string(match1.group(8))

        color_value = match2.group(1)
        marker_value = match2.group(2)
        duration = int(match2.group(3))

        # Buscar el EDLColor por su valor
        color = _parse_edl_color(color_value)
        marker_type = _parse_marker_type(marker_value)

        return cls(
            event_number=event_number,
            reel=reel,
            track=track,
            edit_type=edit_type,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=rec_in,
            rec_out=rec_out,
            color=color,
            marker_type=marker_type,
            duration=duration,
        )


@dataclass
class EDLDocument:
    """Representación completa de un archivo EDL CMX 3600.

    Encapsula la cabecera (TITLE + FCM) y la secuencia de eventos.
    Garantiza round-trip fiel al preservar el formato de columnas.
    """

    title: str
    fcm: str = "NON-DROP FRAME"
    events: list[EDLEvent] = field(default_factory=list)

    def serialize(self) -> str:
        """Serializa documento completo con cabecera TITLE + FCM + eventos.

        Formato:
            TITLE: {title}
            FCM: {fcm}
            (línea vacía)
            {evento 1 línea 1}
            {evento 1 línea 2}
            (línea vacía)
            ...

        Returns:
            String con el contenido completo del archivo .edl
        """
        lines: list[str] = []

        # Cabecera
        lines.append(f"TITLE: {self.title}")
        lines.append(f"FCM: {self.fcm}")
        lines.append("")

        # Eventos
        for event in self.events:
            lines.append(event.to_cmx3600())
            lines.append("")

        return "\n".join(lines) + "\n"

    @classmethod
    def parse(cls, content: str) -> EDLDocument:
        """Parsea archivo EDL completo desde texto.

        Extrae la cabecera TITLE y FCM, y reconstruye la lista
        de eventos a partir de pares de líneas.

        Args:
            content: Contenido completo del archivo .edl

        Returns:
            EDLDocument reconstruido desde el contenido.

        Raises:
            ValueError: Si el contenido no tiene formato EDL válido.
        """
        lines = content.split("\n")

        title = ""
        fcm = "NON-DROP FRAME"
        events: list[EDLEvent] = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Parsear cabecera TITLE
            if line.startswith("TITLE:"):
                title = line[len("TITLE:"):].strip()
                i += 1
                continue

            # Parsear cabecera FCM
            if line.startswith("FCM:"):
                fcm = line[len("FCM:"):].strip()
                i += 1
                continue

            # Intentar parsear evento (línea principal + comentario)
            if _EVENT_LINE_PATTERN.match(line):
                # La siguiente línea debe ser el comentario
                if i + 1 < len(lines) and _COMMENT_LINE_PATTERN.match(lines[i + 1]):
                    event = EDLEvent.from_cmx3600(line, lines[i + 1])
                    events.append(event)
                    i += 2
                    continue

            i += 1

        return cls(title=title, fcm=fcm, events=events)

    def add_event(
        self,
        tc_in: SMPTETimecode,
        color: EDLColor,
        marker_type: MarkerType,
        duration: int = 1,
        reel: str = "001",
        track: str = "V",
        edit_type: str = "C",
    ) -> EDLEvent:
        """Agrega evento con auto-numeración secuencial.

        El tc_out se calcula como tc_in + 1 frame.
        rec_in = tc_in, rec_out = tc_out.
        El número de evento se asigna automáticamente (siguiente secuencial).

        Args:
            tc_in: Timecode de entrada del marcador.
            color: Color del marcador EDL.
            marker_type: Tipo de marcador.
            duration: Duración en frames (default 1).
            reel: Reel ID (default "001").
            track: Track type (default "V").
            edit_type: Tipo de edición (default "C" = cut).

        Returns:
            EDLEvent creado y agregado al documento.
        """
        event_number = len(self.events) + 1
        tc_out = tc_in.advance_frames(duration)

        event = EDLEvent(
            event_number=event_number,
            reel=reel,
            track=track,
            edit_type=edit_type,
            tc_in=tc_in,
            tc_out=tc_out,
            rec_in=tc_in,
            rec_out=tc_out,
            color=color,
            marker_type=marker_type,
            duration=duration,
        )
        self.events.append(event)
        return event


def _parse_edl_color(value: str) -> EDLColor:
    """Parsea un valor de color EDL a su enum correspondiente.

    Args:
        value: String del valor de color (e.g. "ResolveColorRed").

    Returns:
        EDLColor correspondiente.

    Raises:
        ValueError: Si el valor no corresponde a ningún color conocido.
    """
    for color in EDLColor:
        if color.value == value:
            return color
    raise ValueError(f"Color EDL desconocido: '{value}'")


def _parse_marker_type(value: str) -> MarkerType:
    """Parsea un valor de tipo de marcador a su enum correspondiente.

    Args:
        value: String del tipo de marcador (e.g. "ENTRADA").

    Returns:
        MarkerType correspondiente.

    Raises:
        ValueError: Si el valor no corresponde a ningún tipo conocido.
    """
    for mt in MarkerType:
        if mt.value == value:
            return mt
    raise ValueError(f"Tipo de marcador desconocido: '{value}'")
