"""SMPTETimecode — Timecode SMPTE con aritmética de frames y Drop Frame.

Implementa el estándar SMPTE 12M para timecodes con soporte completo
de Drop Frame (29.97 fps) y Non-Drop Frame.

Requisitos: 12.5, 18.3, 18.4
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Regex para parsear timecodes SMPTE: HH:MM:SS:FF o HH:MM:SS;FF
_TIMECODE_PATTERN = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})([;:])(\d{2})$"
)


@dataclass(frozen=True)
class SMPTETimecode:
    """Timecode SMPTE alineado a TOD (Time of Day).

    Soporta Non-Drop Frame (30 fps) y Drop Frame (29.97 fps)
    con aritmética de frames según SMPTE 12M.
    """

    hours: int  # 0-23
    minutes: int  # 0-59
    seconds: int  # 0-59
    frames: int  # 0-(fps-1)
    drop_frame: bool  # True para 29.97 fps

    def __post_init__(self) -> None:
        """Valida rangos de los campos del timecode."""
        if not (0 <= self.hours <= 23):
            raise ValueError(f"hours debe estar entre 0 y 23, recibido: {self.hours}")
        if not (0 <= self.minutes <= 59):
            raise ValueError(f"minutes debe estar entre 0 y 59, recibido: {self.minutes}")
        if not (0 <= self.seconds <= 59):
            raise ValueError(f"seconds debe estar entre 0 y 59, recibido: {self.seconds}")

        max_frames = 29 if self.drop_frame else 29
        if not (0 <= self.frames <= max_frames):
            raise ValueError(
                f"frames debe estar entre 0 y {max_frames}, recibido: {self.frames}"
            )

        # Validar que en drop frame, los frames 0 y 1 no existan
        # en el segundo 0 de minutos que no son múltiplo de 10
        if self.drop_frame and self.seconds == 0 and self.frames < 2:
            if self.minutes % 10 != 0:
                raise ValueError(
                    f"En Drop Frame, frames 0 y 1 no existen en el segundo 0 "
                    f"del minuto {self.minutes} (no es múltiplo de 10)"
                )

    def to_string(self) -> str:
        """Formatea HH:MM:SS:FF o HH:MM:SS;FF (drop frame).

        Usa separador `;` para drop frame y `:` para non-drop frame,
        según requisito 12.5.
        """
        sep = ";" if self.drop_frame else ":"
        return (
            f"{self.hours:02d}:{self.minutes:02d}:"
            f"{self.seconds:02d}{sep}{self.frames:02d}"
        )

    @classmethod
    def from_string(cls, s: str) -> SMPTETimecode:
        """Parsea timecode desde string SMPTE.

        Acepta formatos:
          - HH:MM:SS:FF (non-drop frame)
          - HH:MM:SS;FF (drop frame)

        Raises:
            ValueError: Si el string no tiene formato SMPTE válido.
        """
        match = _TIMECODE_PATTERN.match(s.strip())
        if not match:
            raise ValueError(f"Formato de timecode inválido: '{s}'")

        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        separator = match.group(4)
        frames = int(match.group(5))
        drop_frame = separator == ";"

        return cls(
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            frames=frames,
            drop_frame=drop_frame,
        )

    def advance_frames(self, n: int, fps: float = 0.0) -> SMPTETimecode:
        """Avanza n frames respetando drop frame si aplica.

        Args:
            n: Número de frames a avanzar (puede ser negativo).
            fps: Frecuencia de frames. Si es 0, se usa 29.97 para drop_frame
                 o 30.0 para non-drop frame.

        Returns:
            Nuevo SMPTETimecode avanzado n frames.
        """
        if fps == 0.0:
            fps = 29.97 if self.drop_frame else 30.0

        # Determinar frames nominales por segundo
        nominal_fps = round(fps)

        # Convertir timecode actual a frame count absoluto
        total_frames = self._to_frame_count(nominal_fps)

        # Avanzar
        total_frames += n

        # Manejar wrap-around para TOD (24 horas)
        if self.drop_frame:
            # Total de frames en 24h para drop frame (29.97)
            # 30 * 60 * 60 * 24 - 2 * (60 * 24 - 6 * 24) = frames en 24h
            frames_per_24h = _total_frames_24h_drop()
        else:
            frames_per_24h = nominal_fps * 60 * 60 * 24

        total_frames = total_frames % frames_per_24h

        return SMPTETimecode._from_frame_count(
            total_frames, nominal_fps, self.drop_frame
        )

    def _to_frame_count(self, nominal_fps: int = 30) -> int:
        """Convierte este timecode a un conteo absoluto de frames.

        Para Drop Frame (SMPTE 12M):
        Se calculan los frames totales considerando que se saltan
        2 frames al inicio de cada minuto excepto los múltiplos de 10.

        Args:
            nominal_fps: Frames nominales por segundo (30 para 29.97 DF).

        Returns:
            Conteo absoluto de frames desde 00:00:00:00.
        """
        if self.drop_frame:
            # Algoritmo SMPTE 12M para Drop Frame
            # Frames por hora sin drop = 30 * 3600 = 108000
            # Drops por hora = 2 * (60 - 6) = 108 frames dropped por hora
            # Total minutos transcurridos
            total_minutes = self.hours * 60 + self.minutes
            # Minutos que NO son múltiplo de 10
            non_ten_minutes = total_minutes - (total_minutes // 10)

            frame_count = (
                self.hours * 108000  # 30 * 60 * 60
                + self.minutes * 1800  # 30 * 60
                + self.seconds * 30
                + self.frames
                - 2 * non_ten_minutes
            )
            return frame_count
        else:
            # Non-Drop Frame: cálculo directo
            return (
                self.hours * nominal_fps * 3600
                + self.minutes * nominal_fps * 60
                + self.seconds * nominal_fps
                + self.frames
            )

    @staticmethod
    def _from_frame_count(
        frame_count: int, nominal_fps: int = 30, drop_frame: bool = False
    ) -> SMPTETimecode:
        """Convierte un conteo absoluto de frames a campos de timecode.

        Para Drop Frame, aplica el algoritmo inverso de SMPTE 12M.

        Args:
            frame_count: Conteo absoluto de frames.
            nominal_fps: Frames nominales por segundo.
            drop_frame: Si True, aplica compensación Drop Frame.

        Returns:
            Instancia de SMPTETimecode correspondiente al frame count.
        """
        if drop_frame:
            # Algoritmo inverso SMPTE 12M para Drop Frame
            # Basado en el estándar: 2 frames se saltan por minuto excepto cada 10 min
            drop_frames = 2
            frames_per_sec = 30
            frames_per_min = frames_per_sec * 60  # 1800
            frames_per_10min = frames_per_min * 10  # 18000
            # Frames realmente en 10 minutos con drop:
            # 18000 - 2*9 = 17982
            frames_per_10min_actual = frames_per_10min - (drop_frames * 9)

            # Número de bloques completos de 10 minutos
            d = frame_count // frames_per_10min_actual
            # Frames restantes después de bloques de 10 min
            m = frame_count % frames_per_10min_actual

            if m < frames_per_min:
                # Estamos en el primer minuto del bloque de 10 (minuto múltiplo de 10)
                # No hay drop en este minuto
                adjusted_frames = frame_count + drop_frames * 9 * d
            else:
                # Estamos en minutos 1-9 del bloque
                # Frames después del primer minuto del bloque
                remaining = m - frames_per_min
                # Frames reales por minuto con drop: 1800 - 2 = 1798
                frames_per_min_drop = frames_per_min - drop_frames
                additional_minutes = remaining // frames_per_min_drop
                adjusted_frames = (
                    frame_count
                    + drop_frames * 9 * d
                    + drop_frames * (additional_minutes + 1)
                )

            # Ahora convertir adjusted_frames como si fuera non-drop
            frames = adjusted_frames % frames_per_sec
            seconds = (adjusted_frames // frames_per_sec) % 60
            minutes = (adjusted_frames // frames_per_min) % 60
            hours = (adjusted_frames // (frames_per_min * 60)) % 24

            return SMPTETimecode(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
                frames=frames,
                drop_frame=True,
            )
        else:
            # Non-Drop Frame: cálculo directo inverso
            frames = frame_count % nominal_fps
            seconds = (frame_count // nominal_fps) % 60
            minutes = (frame_count // (nominal_fps * 60)) % 60
            hours = (frame_count // (nominal_fps * 3600)) % 24

            return SMPTETimecode(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
                frames=frames,
                drop_frame=False,
            )


def _total_frames_24h_drop() -> int:
    """Calcula el total de frames en 24 horas para Drop Frame 29.97.

    En 24 horas hay 24 * 60 = 1440 minutos.
    Se saltan 2 frames en cada minuto excepto los múltiplos de 10.
    Minutos múltiplos de 10 en 24h: 1440 / 10 = 144.
    Minutos con drop: 1440 - 144 = 1296.
    Total frames sin drop: 30 * 60 * 60 * 24 = 2592000.
    Total frames drop: 2592000 - 2 * 1296 = 2592000 - 2592 = 2589408.
    """
    return 2592000 - 2 * (1440 - 144)
