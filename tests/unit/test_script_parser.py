"""Tests unitarios para ScriptParser con soporte PDF/MD/JSON."""

import json
import tempfile
from pathlib import Path

import pytest

from switch_bot.engines.script_parser import (
    ScriptBlock,
    ScriptDocument,
    ScriptFormatError,
    ScriptParser,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def parser():
    return ScriptParser()


@pytest.fixture
def sample_json_script(tmp_path: Path) -> Path:
    """Crea un archivo JSON de guión válido."""
    data = {
        "title": "Guión de Prueba",
        "character_camera_map": {"CARLOS": 1, "MARIA": 2, "PEDRO": 3},
        "blocks": [
            {
                "index": 0,
                "character": "CARLOS",
                "text": "Hola, ¿cómo estás?",
                "cue": "saludo",
                "scene": "Interior oficina",
            },
            {
                "index": 1,
                "character": "MARIA",
                "text": "Bien, gracias por preguntar.",
                "cue": None,
                "scene": "Interior oficina",
            },
            {
                "index": 2,
                "character": "PEDRO",
                "text": "Buenos días a todos.",
                "cue": "entrada",
                "scene": "Interior oficina",
            },
        ],
    }
    path = tmp_path / "guion.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def sample_md_script(tmp_path: Path) -> Path:
    """Crea un archivo Markdown de guión válido."""
    content = """# Mi Guión de Producción

ESCENA: Interior oficina

CARLOS: Hola, ¿cómo estás? [saludo]
MARIA: Bien, gracias por preguntar.
PEDRO: Buenos días a todos. [entrada]

ESCENA: Exterior jardín

CARLOS: Qué bonito día hace hoy.
MARIA: Sí, perfecto para grabar.

CÁMARAS: CARLOS=1, MARIA=2, PEDRO=3
"""
    path = tmp_path / "guion.md"
    path.write_text(content, encoding="utf-8")
    return path


# ─── Tests de ScriptDocument ────────────────────────────────────────────────


class TestScriptDocument:
    def test_get_blocks_by_character(self):
        blocks = [
            ScriptBlock(index=0, character="CARLOS", text="Hola"),
            ScriptBlock(index=1, character="MARIA", text="Adiós"),
            ScriptBlock(index=2, character="CARLOS", text="Ciao"),
        ]
        doc = ScriptDocument(
            title="Test", blocks=blocks, character_camera_map={"CARLOS": 1, "MARIA": 2}
        )

        carlos_blocks = doc.get_blocks_by_character("CARLOS")
        assert len(carlos_blocks) == 2
        assert carlos_blocks[0].text == "Hola"
        assert carlos_blocks[1].text == "Ciao"

    def test_get_blocks_by_character_empty(self):
        doc = ScriptDocument(
            title="Test",
            blocks=[ScriptBlock(index=0, character="CARLOS", text="Hola")],
            character_camera_map={"CARLOS": 1},
        )
        assert doc.get_blocks_by_character("NADIE") == []

    def test_get_block_at_index(self):
        blocks = [
            ScriptBlock(index=0, character="CARLOS", text="Hola"),
            ScriptBlock(index=1, character="MARIA", text="Adiós"),
        ]
        doc = ScriptDocument(
            title="Test", blocks=blocks, character_camera_map={}
        )

        block = doc.get_block_at_index(1)
        assert block.character == "MARIA"
        assert block.text == "Adiós"

    def test_get_block_at_index_not_found(self):
        doc = ScriptDocument(
            title="Test",
            blocks=[ScriptBlock(index=0, character="CARLOS", text="Hola")],
            character_camera_map={},
        )
        with pytest.raises(IndexError, match="No existe bloque con índice 99"):
            doc.get_block_at_index(99)


# ─── Tests de carga JSON ────────────────────────────────────────────────────


class TestScriptParserJSON:
    def test_load_json_valid(self, parser: ScriptParser, sample_json_script: Path):
        doc = parser.load(sample_json_script)

        assert doc.title == "Guión de Prueba"
        assert len(doc.blocks) == 3
        assert doc.character_camera_map == {"CARLOS": 1, "MARIA": 2, "PEDRO": 3}

        assert doc.blocks[0].character == "CARLOS"
        assert doc.blocks[0].text == "Hola, ¿cómo estás?"
        assert doc.blocks[0].cue == "saludo"
        assert doc.blocks[0].scene == "Interior oficina"

    def test_load_json_missing_title(self, parser: ScriptParser, tmp_path: Path):
        data = {"blocks": [], "character_camera_map": {}}
        path = tmp_path / "no_title.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ScriptFormatError, match="no tiene campo 'title'"):
            parser.load(path)

    def test_load_json_missing_blocks(self, parser: ScriptParser, tmp_path: Path):
        data = {"title": "Test", "character_camera_map": {}}
        path = tmp_path / "no_blocks.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ScriptFormatError, match="no tiene campo 'blocks'"):
            parser.load(path)

    def test_load_json_missing_camera_map(self, parser: ScriptParser, tmp_path: Path):
        data = {"title": "Test", "blocks": []}
        path = tmp_path / "no_map.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ScriptFormatError, match="no tiene campo 'character_camera_map'"):
            parser.load(path)

    def test_load_json_invalid_syntax(self, parser: ScriptParser, tmp_path: Path):
        path = tmp_path / "invalid.json"
        path.write_text("{not valid json!!!")

        with pytest.raises(ScriptFormatError, match="no contiene JSON válido"):
            parser.load(path)

    def test_load_json_block_missing_character(self, parser: ScriptParser, tmp_path: Path):
        data = {
            "title": "Test",
            "blocks": [{"text": "hello"}],
            "character_camera_map": {},
        }
        path = tmp_path / "bad_block.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ScriptFormatError, match="requiere al menos"):
            parser.load(path)

    def test_load_json_invalid_camera_value(self, parser: ScriptParser, tmp_path: Path):
        data = {
            "title": "Test",
            "blocks": [{"character": "CARLOS", "text": "Hola"}],
            "character_camera_map": {"CARLOS": "not_a_number"},
        }
        path = tmp_path / "bad_cam.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ScriptFormatError, match="debe ser un número entero"):
            parser.load(path)


# ─── Tests de carga Markdown ────────────────────────────────────────────────


class TestScriptParserMarkdown:
    def test_load_markdown_valid(self, parser: ScriptParser, sample_md_script: Path):
        doc = parser.load(sample_md_script)

        assert doc.title == "Mi Guión de Producción"
        assert len(doc.blocks) == 5
        assert doc.character_camera_map == {"CARLOS": 1, "MARIA": 2, "PEDRO": 3}

        # First block
        assert doc.blocks[0].character == "CARLOS"
        assert doc.blocks[0].cue == "saludo"
        assert doc.blocks[0].scene == "Interior oficina"

        # Scene changes
        assert doc.blocks[3].scene == "Exterior jardín"

    def test_load_markdown_empty_file(self, parser: ScriptParser, tmp_path: Path):
        path = tmp_path / "empty.md"
        path.write_text("")

        with pytest.raises(ScriptFormatError, match="está vacío"):
            parser.load(path)

    def test_load_markdown_no_dialogue(self, parser: ScriptParser, tmp_path: Path):
        path = tmp_path / "no_dialogue.md"
        path.write_text("# Título\n\nEsto no tiene diálogo\n")

        with pytest.raises(ScriptFormatError, match="No se encontraron bloques de diálogo"):
            parser.load(path)

    def test_load_markdown_with_cues(self, parser: ScriptParser, tmp_path: Path):
        content = "# Test\n\nCARLOS: Hola mundo [pausa dramática]\n"
        path = tmp_path / "cues.md"
        path.write_text(content)

        doc = parser.load(path)
        assert doc.blocks[0].cue == "pausa dramática"
        assert "pausa dramática" not in doc.blocks[0].text

    def test_load_markdown_camera_mapping(self, parser: ScriptParser, tmp_path: Path):
        content = "# Test\n\nCARLOS: Hola\nMARIA: Adiós\n\nCAMERAS: CARLOS=1, MARIA=2\n"
        path = tmp_path / "cameras.md"
        path.write_text(content)

        doc = parser.load(path)
        assert doc.character_camera_map == {"CARLOS": 1, "MARIA": 2}


# ─── Tests de formato no reconocido ─────────────────────────────────────────


class TestScriptParserErrors:
    def test_unsupported_format(self, parser: ScriptParser, tmp_path: Path):
        path = tmp_path / "script.docx"
        path.write_text("contenido")

        with pytest.raises(ScriptFormatError, match="Formato no reconocido.*\\.docx"):
            parser.load(path)

    def test_file_not_exists(self, parser: ScriptParser):
        with pytest.raises(ScriptFormatError, match="El archivo no existe"):
            parser.load(Path("/tmp/nonexistent_script_xyz.json"))

    def test_get_block_without_load(self, parser: ScriptParser):
        with pytest.raises(ScriptFormatError, match="No hay documento cargado"):
            parser.get_block(0)

    def test_get_character_mapping_without_load(self, parser: ScriptParser):
        with pytest.raises(ScriptFormatError, match="No hay documento cargado"):
            parser.get_character_mapping()


# ─── Tests de get_block y get_character_mapping ──────────────────────────────


class TestScriptParserMethods:
    def test_get_block_after_load(self, parser: ScriptParser, sample_json_script: Path):
        parser.load(sample_json_script)

        block = parser.get_block(0)
        assert block.character == "CARLOS"
        assert block.text == "Hola, ¿cómo estás?"

    def test_get_character_mapping_after_load(
        self, parser: ScriptParser, sample_json_script: Path
    ):
        parser.load(sample_json_script)

        mapping = parser.get_character_mapping()
        assert mapping == {"CARLOS": 1, "MARIA": 2, "PEDRO": 3}

    def test_get_block_invalid_index(
        self, parser: ScriptParser, sample_json_script: Path
    ):
        parser.load(sample_json_script)

        with pytest.raises(IndexError):
            parser.get_block(999)
