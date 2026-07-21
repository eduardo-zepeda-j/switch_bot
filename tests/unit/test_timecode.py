"""Tests unitarios para SMPTETimecode.

Valida aritmética de frames, formato Drop Frame/Non-Drop Frame,
y lógica SMPTE 12M.
"""

import pytest

from switch_bot.models.timecode import SMPTETimecode


class TestToString:
    """Tests para el método to_string()."""

    def test_non_drop_frame_separator(self):
        """Non-Drop Frame usa ':' como separador de frames."""
        tc = SMPTETimecode(1, 2, 3, 4, drop_frame=False)
        assert tc.to_string() == "01:02:03:04"

    def test_drop_frame_separator(self):
        """Drop Frame usa ';' como separador de frames (Req 12.5)."""
        tc = SMPTETimecode(1, 0, 3, 4, drop_frame=True)
        assert tc.to_string() == "01:00:03;04"

    def test_zero_timecode_ndf(self):
        """Timecode cero en non-drop frame."""
        tc = SMPTETimecode(0, 0, 0, 0, drop_frame=False)
        assert tc.to_string() == "00:00:00:00"

    def test_zero_timecode_df(self):
        """Timecode cero en drop frame (minuto 0 es múltiplo de 10)."""
        tc = SMPTETimecode(0, 0, 0, 0, drop_frame=True)
        assert tc.to_string() == "00:00:00;00"

    def test_max_timecode_ndf(self):
        """Timecode máximo en non-drop frame."""
        tc = SMPTETimecode(23, 59, 59, 29, drop_frame=False)
        assert tc.to_string() == "23:59:59:29"

    def test_max_timecode_df(self):
        """Timecode máximo en drop frame."""
        tc = SMPTETimecode(23, 59, 59, 29, drop_frame=True)
        assert tc.to_string() == "23:59:59;29"


class TestFromString:
    """Tests para el método from_string()."""

    def test_parse_non_drop_frame(self):
        """Parsea timecode con separador ':'."""
        tc = SMPTETimecode.from_string("01:02:03:04")
        assert tc.hours == 1
        assert tc.minutes == 2
        assert tc.seconds == 3
        assert tc.frames == 4
        assert tc.drop_frame is False

    def test_parse_drop_frame(self):
        """Parsea timecode con separador ';'."""
        tc = SMPTETimecode.from_string("10:30:15;20")
        assert tc.hours == 10
        assert tc.minutes == 30
        assert tc.seconds == 15
        assert tc.frames == 20
        assert tc.drop_frame is True

    def test_roundtrip_ndf(self):
        """Round-trip: to_string → from_string para NDF."""
        original = SMPTETimecode(12, 34, 56, 28, drop_frame=False)
        parsed = SMPTETimecode.from_string(original.to_string())
        assert parsed == original

    def test_roundtrip_df(self):
        """Round-trip: to_string → from_string para DF."""
        original = SMPTETimecode(12, 30, 56, 28, drop_frame=True)
        parsed = SMPTETimecode.from_string(original.to_string())
        assert parsed == original

    def test_invalid_format_raises(self):
        """Formato inválido lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode.from_string("invalid")

    def test_invalid_format_bad_separators(self):
        """Separadores incorrectos lanzan ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode.from_string("01-02-03-04")


class TestValidation:
    """Tests de validación de rangos."""

    def test_hours_out_of_range(self):
        """hours fuera de rango lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode(24, 0, 0, 0, drop_frame=False)

    def test_minutes_out_of_range(self):
        """minutes fuera de rango lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode(0, 60, 0, 0, drop_frame=False)

    def test_seconds_out_of_range(self):
        """seconds fuera de rango lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode(0, 0, 60, 0, drop_frame=False)

    def test_frames_out_of_range(self):
        """frames fuera de rango lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode(0, 0, 0, 30, drop_frame=False)

    def test_negative_hours(self):
        """hours negativo lanza ValueError."""
        with pytest.raises(ValueError):
            SMPTETimecode(-1, 0, 0, 0, drop_frame=False)

    def test_drop_frame_invalid_frame_0_at_non_ten_minute(self):
        """En DF, frame 0 en segundo 0 de minuto no múltiplo de 10 es inválido."""
        with pytest.raises(ValueError):
            SMPTETimecode(0, 1, 0, 0, drop_frame=True)

    def test_drop_frame_invalid_frame_1_at_non_ten_minute(self):
        """En DF, frame 1 en segundo 0 de minuto no múltiplo de 10 es inválido."""
        with pytest.raises(ValueError):
            SMPTETimecode(0, 1, 0, 1, drop_frame=True)

    def test_drop_frame_valid_frame_0_at_ten_minute(self):
        """En DF, frame 0 en segundo 0 de minuto múltiplo de 10 es válido."""
        tc = SMPTETimecode(0, 10, 0, 0, drop_frame=True)
        assert tc.frames == 0

    def test_drop_frame_valid_frame_2_at_non_ten_minute(self):
        """En DF, frame 2 en segundo 0 de minuto no múltiplo de 10 es válido."""
        tc = SMPTETimecode(0, 1, 0, 2, drop_frame=True)
        assert tc.frames == 2


class TestAdvanceFrames:
    """Tests para advance_frames() con lógica Drop Frame SMPTE 12M."""

    def test_advance_one_frame_ndf(self):
        """Avanzar 1 frame en NDF incrementa el campo frames."""
        tc = SMPTETimecode(0, 0, 0, 0, drop_frame=False)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 0, 0, 1, drop_frame=False)

    def test_advance_rolls_seconds_ndf(self):
        """Avanzar más allá de 29 frames incrementa segundos en NDF."""
        tc = SMPTETimecode(0, 0, 0, 29, drop_frame=False)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 0, 1, 0, drop_frame=False)

    def test_advance_rolls_minutes_ndf(self):
        """Avanzar más allá de 59 segundos incrementa minutos en NDF."""
        tc = SMPTETimecode(0, 0, 59, 29, drop_frame=False)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 1, 0, 0, drop_frame=False)

    def test_advance_rolls_hours_ndf(self):
        """Avanzar más allá de 59 minutos incrementa horas en NDF."""
        tc = SMPTETimecode(0, 59, 59, 29, drop_frame=False)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(1, 0, 0, 0, drop_frame=False)

    def test_advance_drop_frame_skips_frames(self):
        """En DF, al cruzar el minuto 1 se saltan frames 0 y 1."""
        # 00:00:59;29 + 1 frame debe saltar a 00:01:00;02
        tc = SMPTETimecode(0, 0, 59, 29, drop_frame=True)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 1, 0, 2, drop_frame=True)

    def test_advance_drop_frame_no_skip_at_ten_minute(self):
        """En DF, al cruzar un minuto múltiplo de 10 NO se saltan frames."""
        # 00:09:59;29 + 1 frame debe ir a 00:10:00;00
        tc = SMPTETimecode(0, 9, 59, 29, drop_frame=True)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 10, 0, 0, drop_frame=True)

    def test_advance_negative_frames_ndf(self):
        """Retroceder frames en NDF."""
        tc = SMPTETimecode(0, 1, 0, 0, drop_frame=False)
        result = tc.advance_frames(-1)
        assert result == SMPTETimecode(0, 0, 59, 29, drop_frame=False)

    def test_advance_negative_frames_df(self):
        """Retroceder frames en DF respeta los skips."""
        # 00:01:00;02 - 1 debe dar 00:00:59;29
        tc = SMPTETimecode(0, 1, 0, 2, drop_frame=True)
        result = tc.advance_frames(-1)
        assert result == SMPTETimecode(0, 0, 59, 29, drop_frame=True)

    def test_advance_wraps_24h_ndf(self):
        """Al superar 23:59:59:29 en NDF, vuelve a 00:00:00:00 (TOD)."""
        tc = SMPTETimecode(23, 59, 59, 29, drop_frame=False)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 0, 0, 0, drop_frame=False)

    def test_advance_zero_frames(self):
        """Avanzar 0 frames devuelve el mismo timecode."""
        tc = SMPTETimecode(5, 30, 15, 10, drop_frame=False)
        result = tc.advance_frames(0)
        assert result == tc

    def test_advance_one_second_ndf(self):
        """Avanzar 30 frames = 1 segundo en NDF a 30 fps."""
        tc = SMPTETimecode(0, 0, 0, 0, drop_frame=False)
        result = tc.advance_frames(30)
        assert result == SMPTETimecode(0, 0, 1, 0, drop_frame=False)

    def test_drop_frame_minute_2_skip(self):
        """En DF, cruzar al minuto 2 también salta frames 0,1."""
        tc = SMPTETimecode(0, 1, 59, 29, drop_frame=True)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 2, 0, 2, drop_frame=True)

    def test_drop_frame_minute_20_no_skip(self):
        """En DF, cruzar al minuto 20 (múltiplo de 10) no salta frames."""
        tc = SMPTETimecode(0, 19, 59, 29, drop_frame=True)
        result = tc.advance_frames(1)
        assert result == SMPTETimecode(0, 20, 0, 0, drop_frame=True)


class TestFrameCountConversion:
    """Tests para _to_frame_count() y _from_frame_count()."""

    def test_zero_frame_count_ndf(self):
        """Frame count 0 corresponde a 00:00:00:00 NDF."""
        tc = SMPTETimecode(0, 0, 0, 0, drop_frame=False)
        assert tc._to_frame_count(30) == 0

    def test_one_second_frame_count_ndf(self):
        """1 segundo = 30 frames en NDF."""
        tc = SMPTETimecode(0, 0, 1, 0, drop_frame=False)
        assert tc._to_frame_count(30) == 30

    def test_one_minute_frame_count_ndf(self):
        """1 minuto = 1800 frames en NDF."""
        tc = SMPTETimecode(0, 1, 0, 0, drop_frame=False)
        assert tc._to_frame_count(30) == 1800

    def test_one_hour_frame_count_ndf(self):
        """1 hora = 108000 frames en NDF."""
        tc = SMPTETimecode(1, 0, 0, 0, drop_frame=False)
        assert tc._to_frame_count(30) == 108000

    def test_roundtrip_frame_count_ndf(self):
        """Round-trip: to_frame_count → from_frame_count en NDF."""
        tc = SMPTETimecode(12, 34, 56, 28, drop_frame=False)
        count = tc._to_frame_count(30)
        result = SMPTETimecode._from_frame_count(count, 30, False)
        assert result == tc

    def test_roundtrip_frame_count_df(self):
        """Round-trip: to_frame_count → from_frame_count en DF."""
        tc = SMPTETimecode(1, 0, 0, 0, drop_frame=True)
        count = tc._to_frame_count(30)
        result = SMPTETimecode._from_frame_count(count, 30, True)
        assert result == tc

    def test_drop_frame_one_minute_count(self):
        """En DF, minuto 1 con frame 2 tiene frame_count correcto.

        00:01:00;02 en DF debería tener frame count = 1800
        (porque los frames 0,1 se saltan, el frame 2 es el primero del minuto 1,
         y es el frame 1800 en la secuencia absoluta).
        """
        tc = SMPTETimecode(0, 1, 0, 2, drop_frame=True)
        count = tc._to_frame_count(30)
        # Sin drop: 1*1800 + 0*30 + 2 = 1802
        # Con drop: 1802 - 2*1 (1 minuto no múltiplo de 10) = 1800
        assert count == 1800

    def test_drop_frame_ten_minute_count(self):
        """En DF, minuto 10 frame 0 tiene frame_count correcto.

        00:10:00;00 en DF debería tener frame_count = 17982
        (10 minutos * 1800 frames/min - 2*9 drops = 17982).
        """
        tc = SMPTETimecode(0, 10, 0, 0, drop_frame=True)
        count = tc._to_frame_count(30)
        # 10*1800 + 0 - 2*(10 - 1) = 18000 - 18 = 17982
        assert count == 17982
