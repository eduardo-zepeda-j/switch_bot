"""Utilidades de ofuscación de secretos e información de modelos locales.

Proporciona ofuscación mínima (base64 + inversión de bytes) para evitar
almacenar secretos en texto plano en archivos INI de QSettings.
No es criptografía — la seguridad real depende de permisos del filesystem.

También define ModelInfo para representar modelos locales descubiertos.

Requisitos: 1.5, 2.3
"""

from __future__ import annotations

import base64
from dataclasses import dataclass


def obfuscate_secret(secret: str) -> str:
    """Ofusca un secreto para almacenamiento local.

    Aplica inversión de la cadena seguida de codificación base64.
    No es seguridad criptográfica — solo evita exposición en texto plano.

    Args:
        secret: El secreto a ofuscar.

    Returns:
        Cadena ofuscada en base64.
    """
    return base64.b64encode(secret[::-1].encode()).decode()


def deobfuscate_secret(stored: str) -> str:
    """Desofusca un secreto almacenado.

    Revierte la codificación base64 y la inversión de cadena.

    Args:
        stored: La cadena ofuscada almacenada.

    Returns:
        El secreto original en texto plano.
    """
    return base64.b64decode(stored.encode()).decode()[::-1]


@dataclass
class ModelInfo:
    """Información de un modelo local descubierto.

    Attributes:
        id: Identificador del modelo, e.g. "llama3:8b".
        name: Nombre legible, e.g. "Llama 3 8B".
        size_gb: Tamaño en GB, o None si no disponible.
        model_type: Tipo de modelo: "embedding" o "llm".
    """

    id: str
    name: str
    size_gb: float | None
    model_type: str

    def display_text(self) -> str:
        """Texto para mostrar en el dropdown.

        Returns:
            "Name (X.X GB)" si el tamaño está disponible, solo "Name" si no.
        """
        if self.size_gb is not None:
            return f"{self.name} ({self.size_gb:.1f} GB)"
        return self.name
