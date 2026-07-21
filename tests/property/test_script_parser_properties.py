"""Property-based tests para ScriptParser — Documentos con formato inválido generan error descriptivo.

**Property 14: Documentos de guión con formato inválido generan error descriptivo**
**Validates: Requirements 3.4**
"""

from __future__ import annotations

import json
import string
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    text,
    sampled_from,
    composite,
)

from switch_bot.engines.script_parser import ScriptFormatError, ScriptParser


# --- Strategies ---

# Extensions que NO son soportadas por ScriptParser
unsupported_extensions = sampled_from([
    ".txt", ".docx", ".html", ".xml", ".csv", ".rtf", ".odt",
    ".pptx", ".xlsx", ".yaml", ".toml", ".ini", ".cfg", ".log",
])

# Texto que no es JSON válido (no empieza con { o [)
invalid_json_content = text(
    alphabet=string.ascii_letters + string.digits + " ,.",
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip() and not s.strip().startswith(("{", "[")))


# JSON válido pero sin estructura esperada (falta title, blocks, character_camera_map)
@composite
def json_missing_required_fields(draw):
    """Genera JSON válido pero sin los campos requeridos del guión."""
    include_title = draw(sampled_from([True, False]))
    include_blocks = draw(sampled_from([True, False]))
    include_map = draw(sampled_from([True, False]))

    # Al menos uno de los campos requeridos debe estar ausente
    assume(not (include_title and include_blocks and include_map))

    obj: dict = {}
    if include_title:
        obj["title"] = "Test Script"
    if include_blocks:
        obj["blocks"] = [{"character": "A", "text": "hola"}]
    if include_map:
        obj["character_camera_map"] = {"A": 1}

    return json.dumps(obj)


# JSON con bloques que no tienen los campos character o text requeridos
@composite
def json_invalid_blocks(draw):
    """Genera JSON con bloques que carecen de campos obligatorios."""
    invalid_block = draw(sampled_from([
        {},
        {"character": "A"},
        {"text": "hello"},
        {"something": "else", "other": 123},
    ]))

    obj = {
        "title": "Test Script",
        "character_camera_map": {"A": 1},
        "blocks": [invalid_block],
    }
    return json.dumps(obj)


# JSON con character_camera_map donde los valores no son enteros
@composite
def json_invalid_camera_values(draw):
    """Genera JSON con valores de cámara no enteros."""
    invalid_val = draw(sampled_from(["one", "2", 3.5, True, None, [1]]))

    obj = {
        "title": "Test Script",
        "character_camera_map": {"PERSONAJE": invalid_val},
        "blocks": [{"character": "PERSONAJE", "text": "hola"}],
    }
    return json.dumps(obj)


# --- Helper ---

def _write_temp_file(suffix: str, content: str) -> Path:
    """Crea un archivo temporal con el sufijo y contenido dados."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


class TestProperty14InvalidScriptFormat:
    """Property 14: Documentos de guión con formato inválido generan error descriptivo.

    FOR ALL documentos con formato inválido, ScriptParser.load() SHALL lanzar
    ScriptFormatError con un mensaje descriptivo indicando el formato esperado
    o el problema encontrado.

    **Validates: Requirements 3.4**
    """

    @given(ext=unsupported_extensions)
    def test_unsupported_extension_raises_descriptive_error(self, ext: str) -> None:
        """FOR ALL extensiones no soportadas, ScriptParser lanza ScriptFormatError
        con mensaje que indica los formatos soportados."""
        file = _write_temp_file(ext, "some content")
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe mencionar el formato no reconocido
            assert "no reconocido" in error_msg.lower() or "formato" in error_msg.lower()
            # Debe listar los formatos soportados
            assert ".pdf" in error_msg or ".md" in error_msg or ".json" in error_msg
        finally:
            file.unlink(missing_ok=True)

    @given(content=invalid_json_content)
    def test_invalid_json_content_raises_descriptive_error(self, content: str) -> None:
        """FOR ALL contenido que no es JSON válido en un archivo .json,
        ScriptParser lanza ScriptFormatError con mensaje descriptivo."""
        file = _write_temp_file(".json", content)
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe mencionar que no es JSON válido
            assert "json" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    @given(content=json_missing_required_fields())
    def test_json_missing_required_fields_raises_descriptive_error(
        self, content: str
    ) -> None:
        """FOR ALL JSON válido sin campos requeridos (title, blocks, character_camera_map),
        ScriptParser lanza ScriptFormatError con mensaje descriptivo."""
        file = _write_temp_file(".json", content)
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe indicar el campo faltante
            assert (
                "title" in error_msg.lower()
                or "blocks" in error_msg.lower()
                or "character_camera_map" in error_msg.lower()
            )
        finally:
            file.unlink(missing_ok=True)

    @given(content=json_invalid_blocks())
    def test_json_blocks_without_required_fields_raises_error(
        self, content: str
    ) -> None:
        """FOR ALL JSON con bloques sin campos 'character' o 'text',
        ScriptParser lanza ScriptFormatError con mensaje descriptivo."""
        file = _write_temp_file(".json", content)
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe mencionar los campos requeridos del bloque
            assert "character" in error_msg.lower() or "text" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    @given(content=json_invalid_camera_values())
    def test_json_invalid_camera_map_values_raises_error(self, content: str) -> None:
        """FOR ALL JSON con valores de cámara no enteros en character_camera_map,
        ScriptParser lanza ScriptFormatError con mensaje descriptivo."""
        file = _write_temp_file(".json", content)
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe indicar que se esperaba un entero
            assert "entero" in error_msg.lower() or "número" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    def test_empty_markdown_file_raises_descriptive_error(self) -> None:
        """Un archivo .md vacío genera ScriptFormatError descriptivo."""
        file = _write_temp_file(".md", "")
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            assert "vacío" in error_msg.lower() or "empty" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    def test_markdown_without_dialogue_raises_descriptive_error(self) -> None:
        """Un archivo .md sin bloques de diálogo genera ScriptFormatError descriptivo."""
        content = "# Mi Guión\n\nEsta es una descripción.\nSin diálogos válidos aquí.\n"
        file = _write_temp_file(".md", content)
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            # Debe indicar que no se encontraron bloques de diálogo
            assert "bloque" in error_msg.lower() or "diálogo" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    def test_nonexistent_file_raises_descriptive_error(self) -> None:
        """Un archivo que no existe genera ScriptFormatError descriptivo."""
        file = Path("/tmp/nonexistent_script_abc123xyz.json")

        parser = ScriptParser()
        with pytest.raises(ScriptFormatError) as exc_info:
            parser.load(file)

        error_msg = str(exc_info.value)
        assert "no existe" in error_msg.lower() or "not found" in error_msg.lower()

    def test_json_root_is_array_raises_descriptive_error(self) -> None:
        """Un archivo .json con un array en la raíz genera ScriptFormatError."""
        file = _write_temp_file(".json", '[{"key": "value"}]')
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            error_msg = str(exc_info.value)
            assert "objeto" in error_msg.lower() or "json" in error_msg.lower()
        finally:
            file.unlink(missing_ok=True)

    @given(ext=unsupported_extensions)
    def test_error_message_is_non_empty_string(self, ext: str) -> None:
        """FOR ALL formatos inválidos, el mensaje de error es un string no vacío."""
        file = _write_temp_file(ext, "dummy")
        try:
            parser = ScriptParser()
            with pytest.raises(ScriptFormatError) as exc_info:
                parser.load(file)

            assert str(exc_info.value).strip() != ""
            assert len(str(exc_info.value)) > 10  # Mensaje descriptivo, no trivial
        finally:
            file.unlink(missing_ok=True)
