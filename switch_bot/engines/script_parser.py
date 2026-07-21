"""ScriptParser — Carga y estructura guiones de producción.

Soporta documentos en formato PDF (via pdfplumber), Markdown y JSON.
Genera una representación en memoria indexada por bloques y personajes
para comparación en tiempo real.

Requisitos: 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Excepciones ─────────────────────────────────────────────────────────────


class ScriptFormatError(Exception):
    """Error lanzado cuando el formato del documento de guión es inválido.

    Contiene un mensaje descriptivo indicando el formato esperado
    y el problema encontrado (Requisito 3.4).
    """

    pass


# ─── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class ScriptBlock:
    """Un bloque individual del guión de producción.

    Representa una línea de diálogo o acción asociada a un personaje,
    con cue opcional y escena.

    Attributes:
        index: Índice secuencial del bloque dentro del documento.
        character: Nombre del personaje que habla/actúa.
        text: Texto del diálogo o acción.
        cue: Indicación escénica opcional (e.g. "saludo", "pausa dramática").
        scene: Escena a la que pertenece el bloque.
    """

    index: int
    character: str
    text: str
    cue: Optional[str] = None
    scene: Optional[str] = None


@dataclass
class ScriptDocument:
    """Representación en memoria de un guión completo.

    Indexado por bloques y personajes para búsqueda eficiente.
    Generado por ScriptParser.load() (Requisito 3.3).

    Attributes:
        title: Título del guión.
        blocks: Lista ordenada de bloques del guión.
        character_camera_map: Mapeo personaje → cámara asignada.
    """

    title: str
    blocks: list[ScriptBlock] = field(default_factory=list)
    character_camera_map: dict[str, int] = field(default_factory=dict)

    def get_blocks_by_character(self, character: str) -> list[ScriptBlock]:
        """Retorna todos los bloques asociados a un personaje.

        Args:
            character: Nombre del personaje a buscar.

        Returns:
            Lista de bloques del personaje (vacía si no existe).
        """
        return [b for b in self.blocks if b.character == character]

    def get_block_at_index(self, index: int) -> ScriptBlock:
        """Obtiene un bloque por su índice.

        Args:
            index: Índice del bloque a buscar.

        Returns:
            El ScriptBlock con el índice solicitado.

        Raises:
            IndexError: Si no existe un bloque con ese índice.
        """
        for block in self.blocks:
            if block.index == index:
                return block
        raise IndexError(f"No existe bloque con índice {index}")


# ─── Regex para parsing de Markdown ──────────────────────────────────────────

# Línea de diálogo: PERSONAJE: texto [cue opcional]
_DIALOGUE_PATTERN = re.compile(
    r"^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9_ ]*?)\s*:\s*(.+)$"
)

# Indicación de escena: ESCENA: descripción
_SCENE_PATTERN = re.compile(
    r"^ESCENA\s*:\s*(.+)$", re.IGNORECASE
)

# Mapeo de cámaras: CAMARAS: NOMBRE=N, NOMBRE=N  (acepta CÁMARAS y CAMERAS)
_CAMERAS_PATTERN = re.compile(
    r"^(?:CÁMARAS|CAMARAS|CAMERAS)\s*:\s*(.+)$", re.IGNORECASE
)

# Cue entre corchetes al final: [texto del cue]
_CUE_PATTERN = re.compile(r"\[([^\]]+)\]\s*$")

# Título en Markdown: # Título
_MD_TITLE_PATTERN = re.compile(r"^#\s+(.+)$")


# ─── ScriptParser ────────────────────────────────────────────────────────────


class ScriptParser:
    """Carga y estructura guiones de producción.

    Soporta formatos PDF, Markdown (.md) y JSON.
    Lanza ScriptFormatError con mensaje descriptivo si el formato
    es inválido o no reconocido (Requisito 3.4).
    """

    def __init__(self) -> None:
        self._document: ScriptDocument | None = None

    def load(self, path: Path) -> ScriptDocument:
        """Carga un documento de guión desde disco.

        Detecta el formato por extensión de archivo:
        - .json → JSON directo
        - .md → Markdown parsing de texto
        - .pdf → PDF via pdfplumber

        Args:
            path: Ruta al archivo del guión.

        Returns:
            ScriptDocument con la representación en memoria.

        Raises:
            ScriptFormatError: Si el archivo no existe, no se reconoce
                el formato o el contenido es inválido.
        """
        path = Path(path)

        if not path.exists():
            raise ScriptFormatError(
                f"El archivo no existe: {path}"
            )

        suffix = path.suffix.lower()

        if suffix == ".json":
            doc = self._load_json(path)
        elif suffix == ".md":
            doc = self._load_markdown(path)
        elif suffix == ".pdf":
            doc = self._load_pdf(path)
        else:
            raise ScriptFormatError(
                f"Formato no reconocido: '{suffix}'. "
                f"Formatos soportados: .pdf, .md, .json"
            )

        self._document = doc
        return doc

    def get_block(self, index: int) -> ScriptBlock:
        """Obtiene un bloque de guión por índice.

        Args:
            index: Índice del bloque a obtener.

        Returns:
            El ScriptBlock correspondiente.

        Raises:
            ScriptFormatError: Si no hay documento cargado.
            IndexError: Si el índice no existe.
        """
        if self._document is None:
            raise ScriptFormatError("No hay documento cargado. Use load() primero.")
        return self._document.get_block_at_index(index)

    def get_character_mapping(self) -> dict[str, int]:
        """Retorna el mapeo personaje → cámara del documento cargado.

        Returns:
            Diccionario con mapeo personaje → número de cámara.

        Raises:
            ScriptFormatError: Si no hay documento cargado.
        """
        if self._document is None:
            raise ScriptFormatError("No hay documento cargado. Use load() primero.")
        return self._document.character_camera_map

    # ─── Loaders privados ────────────────────────────────────────────────────

    def _load_json(self, path: Path) -> ScriptDocument:
        """Carga un guión desde formato JSON.

        Estructura esperada:
        {
            "title": "...",
            "character_camera_map": {"PERSONAJE": cam_index, ...},
            "blocks": [
                {"index": N, "character": "...", "text": "...", "cue": "...", "scene": "..."},
                ...
            ]
        }
        """
        content = path.read_text(encoding="utf-8")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ScriptFormatError(
                f"El archivo '{path.name}' no contiene JSON válido: {e}"
            )

        if not isinstance(data, dict):
            raise ScriptFormatError(
                f"El archivo '{path.name}' debe contener un objeto JSON en la raíz."
            )

        # Validar campos requeridos
        if "title" not in data:
            raise ScriptFormatError(
                f"El archivo '{path.name}' no tiene campo 'title' requerido."
            )
        if "blocks" not in data:
            raise ScriptFormatError(
                f"El archivo '{path.name}' no tiene campo 'blocks' requerido."
            )
        if "character_camera_map" not in data:
            raise ScriptFormatError(
                f"El archivo '{path.name}' no tiene campo 'character_camera_map' requerido."
            )

        # Validar character_camera_map
        camera_map: dict[str, int] = {}
        for name, cam in data["character_camera_map"].items():
            if not isinstance(cam, int) or isinstance(cam, bool):
                raise ScriptFormatError(
                    f"El valor de cámara para '{name}' debe ser un número entero, "
                    f"recibido: {type(cam).__name__} ({cam!r})"
                )
            camera_map[name] = cam

        # Parsear bloques
        blocks: list[ScriptBlock] = []
        for i, block_data in enumerate(data["blocks"]):
            if not isinstance(block_data, dict):
                raise ScriptFormatError(
                    f"El bloque {i} debe ser un objeto JSON."
                )
            if "character" not in block_data or "text" not in block_data:
                raise ScriptFormatError(
                    f"El bloque {i} requiere al menos los campos 'character' y 'text'."
                )

            blocks.append(
                ScriptBlock(
                    index=block_data.get("index", i),
                    character=block_data["character"],
                    text=block_data["text"],
                    cue=block_data.get("cue"),
                    scene=block_data.get("scene"),
                )
            )

        return ScriptDocument(
            title=data["title"],
            blocks=blocks,
            character_camera_map=camera_map,
        )

    def _load_markdown(self, path: Path) -> ScriptDocument:
        """Carga un guión desde formato Markdown.

        Formato esperado:
        - # Título (primera línea con #)
        - ESCENA: nombre de escena
        - PERSONAJE: diálogo [cue opcional]
        - CÁMARAS: PERSONAJE=N, PERSONAJE=N
        """
        content = path.read_text(encoding="utf-8")

        if not content.strip():
            raise ScriptFormatError(
                f"El archivo '{path.name}' está vacío."
            )

        lines = content.split("\n")
        title: str = ""
        blocks: list[ScriptBlock] = []
        camera_map: dict[str, int] = {}
        current_scene: str | None = None
        block_index = 0

        for line in lines:
            line_stripped = line.strip()

            if not line_stripped:
                continue

            # Título del guión (primer encabezado #)
            title_match = _MD_TITLE_PATTERN.match(line_stripped)
            if title_match and not title:
                title = title_match.group(1).strip()
                continue

            # Escena
            scene_match = _SCENE_PATTERN.match(line_stripped)
            if scene_match:
                current_scene = scene_match.group(1).strip()
                continue

            # Mapeo de cámaras
            cameras_match = _CAMERAS_PATTERN.match(line_stripped)
            if cameras_match:
                camera_str = cameras_match.group(1)
                for pair in camera_str.split(","):
                    pair = pair.strip()
                    if "=" in pair:
                        name, cam_str = pair.split("=", 1)
                        name = name.strip()
                        try:
                            camera_map[name] = int(cam_str.strip())
                        except ValueError:
                            pass  # Skip invalid camera values
                continue

            # Diálogo
            dialogue_match = _DIALOGUE_PATTERN.match(line_stripped)
            if dialogue_match:
                character = dialogue_match.group(1).strip()
                text = dialogue_match.group(2).strip()

                # Extraer cue si existe entre corchetes
                cue: str | None = None
                cue_match = _CUE_PATTERN.search(text)
                if cue_match:
                    cue = cue_match.group(1)
                    # Remover el cue del texto
                    text = text[: cue_match.start()].strip()

                blocks.append(
                    ScriptBlock(
                        index=block_index,
                        character=character,
                        text=text,
                        cue=cue,
                        scene=current_scene,
                    )
                )
                block_index += 1

        if not blocks:
            raise ScriptFormatError(
                f"No se encontraron bloques de diálogo en '{path.name}'. "
                f"Formato esperado: 'PERSONAJE: diálogo'"
            )

        if not title:
            title = path.stem

        return ScriptDocument(
            title=title,
            blocks=blocks,
            character_camera_map=camera_map,
        )

    def _load_pdf(self, path: Path) -> ScriptDocument:
        """Carga un guión desde formato PDF usando pdfplumber.

        Extrae el texto completo del PDF y lo parsea con las mismas
        reglas que Markdown (diálogos, escenas, cámaras).
        """
        try:
            import pdfplumber
        except ImportError:
            raise ScriptFormatError(
                "Se requiere 'pdfplumber' para cargar guiones PDF. "
                "Instale con: pip install pdfplumber"
            )

        try:
            with pdfplumber.open(path) as pdf:
                full_text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
        except Exception as e:
            raise ScriptFormatError(
                f"Error al leer el archivo PDF '{path.name}': {e}"
            )

        if not full_text.strip():
            raise ScriptFormatError(
                f"El archivo PDF '{path.name}' no contiene texto extraíble."
            )

        # Parsear el texto extraído con las mismas reglas que Markdown
        lines = full_text.split("\n")
        title: str = ""
        blocks: list[ScriptBlock] = []
        camera_map: dict[str, int] = {}
        current_scene: str | None = None
        block_index = 0

        for line in lines:
            line_stripped = line.strip()

            if not line_stripped:
                continue

            # Título (primer encabezado # o primera línea en mayúsculas)
            title_match = _MD_TITLE_PATTERN.match(line_stripped)
            if title_match and not title:
                title = title_match.group(1).strip()
                continue

            # Escena
            scene_match = _SCENE_PATTERN.match(line_stripped)
            if scene_match:
                current_scene = scene_match.group(1).strip()
                continue

            # Mapeo de cámaras
            cameras_match = _CAMERAS_PATTERN.match(line_stripped)
            if cameras_match:
                camera_str = cameras_match.group(1)
                for pair in camera_str.split(","):
                    pair = pair.strip()
                    if "=" in pair:
                        name, cam_str = pair.split("=", 1)
                        name = name.strip()
                        try:
                            camera_map[name] = int(cam_str.strip())
                        except ValueError:
                            pass
                continue

            # Diálogo
            dialogue_match = _DIALOGUE_PATTERN.match(line_stripped)
            if dialogue_match:
                character = dialogue_match.group(1).strip()
                text = dialogue_match.group(2).strip()

                cue: str | None = None
                cue_match = _CUE_PATTERN.search(text)
                if cue_match:
                    cue = cue_match.group(1)
                    text = text[: cue_match.start()].strip()

                blocks.append(
                    ScriptBlock(
                        index=block_index,
                        character=character,
                        text=text,
                        cue=cue,
                        scene=current_scene,
                    )
                )
                block_index += 1

        if not blocks:
            raise ScriptFormatError(
                f"No se encontraron bloques de diálogo en el PDF '{path.name}'. "
                f"Formato esperado: 'PERSONAJE: diálogo'"
            )

        if not title:
            title = path.stem

        return ScriptDocument(
            title=title,
            blocks=blocks,
            character_camera_map=camera_map,
        )
