"""IAEnricher — Orquestador de enriquecimiento semántico agnóstico al backend.

Utiliza la interfaz IABackend (Strategy Pattern) para delegar operaciones
de embeddings y LLM. Produce resultados con estructura idéntica
independientemente del backend activo (Bedrock o Local).

Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.8, 17.1, 17.2, 17.3, 17.4
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from switch_bot.engines.script_parser import ScriptBlock, ScriptDocument
from switch_bot.ia.backend_base import (
    BackendConnectionError,
    BackendTimeoutError,
    IABackend,
)
from switch_bot.ia.enrichment_result import (
    DEFAULT_DEVIATION_THRESHOLD,
    EnrichmentResult,
)
from switch_bot.models.enums import EDLColor, MarkerType, SourceOrigin
from switch_bot.models.timecode import SMPTETimecode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class VectorStore:
    """Almacén en memoria de embeddings de bloques de guión.

    Permite búsqueda por similitud coseno para encontrar los bloques
    más cercanos a una consulta vectorizada.
    """

    embeddings: list[list[float]]
    blocks: list[ScriptBlock]

    def find_closest(
        self, query_embedding: list[float], top_k: int = 1
    ) -> list[tuple[ScriptBlock, float]]:
        """Encuentra los top_k bloques más cercanos al embedding de consulta.

        Usa similitud coseno entre vectores.

        Args:
            query_embedding: Vector de la consulta.
            top_k: Número de resultados a retornar.

        Returns:
            Lista de tuplas (ScriptBlock, similarity_score) ordenadas por
            similitud descendente.
        """
        if not self.embeddings:
            return []

        scores: list[tuple[int, float]] = []
        for i, emb in enumerate(self.embeddings):
            score = _cosine_similarity(query_embedding, emb)
            scores.append((i, score))

        # Ordenar por similitud descendente
        scores.sort(key=lambda x: x[1], reverse=True)

        results: list[tuple[ScriptBlock, float]] = []
        for idx, score in scores[:top_k]:
            results.append((self.blocks[idx], score))

        return results


@dataclass
class MarkerEvent:
    """Evento de marcador generado por el IAEnricher.

    Representa un marcador EDL con formato CMX 3600 listo para exportación.

    Attributes:
        marker_type: Tipo de marcador EDL.
        color: Color del marcador para DaVinci Resolve.
        note: Nota descriptiva del evento.
        tc: Timecode SMPTE del evento.
        source_origin: Origen del evento.
        cmx_comment: Comentario formateado CMX 3600: |C:{Color} |M:{TYPE} |D:1
    """

    marker_type: MarkerType
    color: EDLColor
    note: str
    tc: SMPTETimecode
    source_origin: SourceOrigin
    cmx_comment: str


@dataclass
class AdSuggestion:
    """Sugerencia publicitaria generada por análisis de sesión.

    Cada sugerencia incluye timecodes de referencia al segmento de video,
    texto propuesto y score de relevancia.

    Attributes:
        tc_in: Timecode SMPTE de inicio del segmento sugerido.
        tc_out: Timecode SMPTE de fin del segmento sugerido.
        text: Texto propuesto para el anuncio.
        relevance_score: Score de relevancia del segmento [0.0, 1.0].
    """

    tc_in: SMPTETimecode
    tc_out: SMPTETimecode
    text: str
    relevance_score: float


# ---------------------------------------------------------------------------
# IAEnricher
# ---------------------------------------------------------------------------


class IAEnricher:
    """Enriquecimiento semántico agnóstico al backend de IA.

    Utiliza la interfaz IABackend para delegar operaciones de embeddings y LLM.
    Produce resultados con estructura idéntica independientemente del backend activo.

    Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.8, 17.1, 17.2, 17.3, 17.4
    """

    def __init__(self, backend: IABackend, script_doc: ScriptDocument) -> None:
        """Inicializa el enriquecedor con un backend y documento de guión.

        Args:
            backend: Implementación concreta de IABackend (Bedrock o Local).
            script_doc: Documento de guión ya parseado.
        """
        self._backend = backend
        self._script_doc = script_doc
        self._vector_store: VectorStore | None = None
        self._similarity_threshold: float = DEFAULT_DEVIATION_THRESHOLD
        self._prompt_timeout_seconds: float = 10.0

    @property
    def active_backend(self) -> IABackend:
        """Retorna el backend activo (solo lectura durante sesión)."""
        return self._backend

    @property
    def vector_store(self) -> VectorStore | None:
        """Retorna el VectorStore actual si el guión fue vectorizado."""
        return self._vector_store

    # ------------------------------------------------------------------
    # Req 6.1 — Vectorizar guión
    # ------------------------------------------------------------------

    async def vectorize_script(self, script: ScriptDocument) -> VectorStore:
        """Genera embeddings del guión completo usando el backend activo como base RAG.

        Vectoriza cada bloque del guión para búsqueda semántica posterior.

        Args:
            script: Documento de guión a vectorizar.

        Returns:
            VectorStore con embeddings y bloques correspondientes.

        Raises:
            BackendConnectionError: Si el backend no está conectado (propagada).
            BackendTimeoutError: Si la generación de embeddings excede timeout.
        """
        texts = [block.text for block in script.blocks]

        if not texts:
            store = VectorStore(embeddings=[], blocks=[])
            self._vector_store = store
            return store

        try:
            embeddings = await self._backend.generate_embeddings(texts)
        except (BackendConnectionError, BackendTimeoutError) as e:
            logger.error(
                "Error vectorizando guión '%s': %s", script.title, e
            )
            raise

        store = VectorStore(embeddings=embeddings, blocks=list(script.blocks))
        self._vector_store = store
        return store

    # ------------------------------------------------------------------
    # Req 6.2, 6.3, 6.8 — Comparar audio en vivo
    # ------------------------------------------------------------------

    async def compare_live_audio(
        self, transcript: str, context: ScriptBlock
    ) -> EnrichmentResult:
        """Compara transcripción live vs. guión con el backend activo.

        Retorna score de similitud semántica [0.0, 1.0].
        Si score < 0.7, genera marcador SCRIPT_DEVIATION con metadatos.
        Si el backend falla, registra error y continúa sin detener la sesión.

        Args:
            transcript: Texto transcrito del segmento de audio en vivo.
            context: Bloque del guión esperado para comparación.

        Returns:
            EnrichmentResult con score, desviación y metadatos.
        """
        try:
            score = await self._backend.compute_similarity(
                transcript, context.text
            )
        except (BackendConnectionError, BackendTimeoutError) as e:
            # Req 6.8: log con SMPTE_TC y continuar sin detener sesión
            logger.error(
                "Error backend comparando audio [bloque %d]: %s — "
                "continuando sin detener sesión",
                context.index,
                e,
            )
            # Retornar resultado con score 0 indicando fallo de backend
            return EnrichmentResult(
                similarity_score=0.0,
                is_deviation=True,
                detected_text=transcript,
                expected_text=context.text,
                marker_type=MarkerType.SCRIPT_DEVIATION,
                color=EDLColor.Magenta,
                metadata={
                    "error": str(e),
                    "backend_failure": True,
                    "block_index": context.index,
                },
            )

        # Clamp score to valid range
        score = max(0.0, min(1.0, score))

        metadata = {
            "block_index": context.index,
            "character": context.character,
            "backend_type": self._backend.backend_type,
        }

        if score < self._similarity_threshold:
            # Req 6.3: score < 0.7 → SCRIPT_DEVIATION
            return EnrichmentResult.from_deviation(
                similarity_score=score,
                detected_text=transcript,
                expected_text=context.text,
                metadata={**metadata, "score": score},
            )
        else:
            return EnrichmentResult.from_match(
                similarity_score=score,
                detected_text=transcript,
                expected_text=context.text,
                metadata={**metadata, "score": score},
            )

    # ------------------------------------------------------------------
    # Req 6.4, 6.5 — Prompt manual del operador
    # ------------------------------------------------------------------

    async def process_manual_prompt(
        self, prompt: str, tc: SMPTETimecode
    ) -> MarkerEvent:
        """Procesa prompt manual del operador con timeout de 10 segundos.

        Genera marcador AI_PROMPT con color Magenta y formato CMX 3600.

        Args:
            prompt: Texto del prompt del operador.
            tc: Timecode SMPTE del momento del prompt.

        Returns:
            MarkerEvent con tipo AI_PROMPT, color Magenta y nota generada.
        """
        note: str

        try:
            response = await asyncio.wait_for(
                self._backend.analyze_context(
                    prompt=prompt,
                    context=f"Guión: {self._script_doc.title}",
                ),
                timeout=self._prompt_timeout_seconds,
            )
            note = response
        except asyncio.TimeoutError:
            logger.error(
                "Timeout procesando prompt manual en TC %s: '%s'",
                tc.to_string(),
                prompt,
            )
            note = f"[TIMEOUT] {prompt}"
        except (BackendConnectionError, BackendTimeoutError) as e:
            # Req 6.8: log con SMPTE_TC y continuar
            logger.error(
                "Error backend procesando prompt en TC %s: %s",
                tc.to_string(),
                e,
            )
            note = f"[ERROR] {prompt}"

        # Req 6.5: Formato CMX 3600
        cmx_comment = _format_cmx_comment(EDLColor.Magenta, MarkerType.AI_PROMPT)

        return MarkerEvent(
            marker_type=MarkerType.AI_PROMPT,
            color=EDLColor.Magenta,
            note=note,
            tc=tc,
            source_origin=SourceOrigin.AI,
            cmx_comment=cmx_comment,
        )

    # ------------------------------------------------------------------
    # Req 17.1, 17.2, 17.3, 17.4 — Sugerencias publicitarias
    # ------------------------------------------------------------------

    async def generate_ad_suggestions(
        self, session_log: Path, script: ScriptDocument
    ) -> list[AdSuggestion]:
        """Genera 3 sugerencias publicitarias post-sesión usando el backend activo.

        Analiza el log de sesión y el guión para identificar los momentos
        de mayor relevancia y menor anomalía vocal.

        Args:
            session_log: Ruta al archivo .jsonl con el log de la sesión.
            script: Documento de guión de referencia.

        Returns:
            Lista de exactamente 3 AdSuggestion con tc_in < tc_out,
            duración entre 15-30 segundos cada una.
        """
        # Cargar y analizar el log de sesión
        log_entries = _load_session_log(session_log)

        # Identificar segmentos con alta densidad de SCRIPT_MATCH
        # y baja incidencia de anomalías vocales (Req 17.4)
        ranked_segments = _rank_segments_for_ads(log_entries)

        # Generar texto de sugerencia usando el backend
        suggestions: list[AdSuggestion] = []

        for segment in ranked_segments[:3]:
            tc_in = segment["tc_in"]
            tc_out = segment["tc_out"]
            relevance = segment["relevance_score"]

            try:
                ad_text = await self._backend.analyze_context(
                    prompt=(
                        "Genera un texto publicitario breve (1-2 frases) para un "
                        "espacio de 15-30 segundos basado en el siguiente contexto "
                        "de contenido televisivo."
                    ),
                    context=(
                        f"Programa: {script.title}\n"
                        f"Segmento: {segment.get('context', '')}\n"
                        f"Relevancia: {relevance:.2f}"
                    ),
                )
            except (BackendConnectionError, BackendTimeoutError) as e:
                logger.error(
                    "Error generando sugerencia publicitaria en TC %s: %s",
                    tc_in.to_string(),
                    e,
                )
                ad_text = f"Espacio publicitario sugerido — {script.title}"

            suggestions.append(
                AdSuggestion(
                    tc_in=tc_in,
                    tc_out=tc_out,
                    text=ad_text,
                    relevance_score=relevance,
                )
            )

        # Si no hay suficientes segmentos del log, generar con defaults
        while len(suggestions) < 3:
            # Generar sugerencia basada en posición relativa en el guión
            idx = len(suggestions)
            # Espaciar las sugerencias a lo largo del programa
            base_minutes = 10 + (idx * 15)
            tc_in = SMPTETimecode(
                hours=0, minutes=base_minutes, seconds=0,
                frames=0, drop_frame=False,
            )
            # Duración: 20 segundos (dentro del rango 15-30s)
            tc_out = SMPTETimecode(
                hours=0, minutes=base_minutes, seconds=20,
                frames=0, drop_frame=False,
            )

            try:
                ad_text = await self._backend.analyze_context(
                    prompt=(
                        "Genera un texto publicitario breve (1-2 frases) para un "
                        "espacio de 20 segundos."
                    ),
                    context=f"Programa: {script.title}",
                )
            except (BackendConnectionError, BackendTimeoutError) as e:
                logger.error(
                    "Error generando sugerencia publicitaria default: %s", e
                )
                ad_text = f"Espacio publicitario — {script.title}"

            suggestions.append(
                AdSuggestion(
                    tc_in=tc_in,
                    tc_out=tc_out,
                    text=ad_text,
                    relevance_score=0.5,
                )
            )

        return suggestions[:3]


# ---------------------------------------------------------------------------
# Funciones auxiliares privadas
# ---------------------------------------------------------------------------


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calcula similitud coseno entre dos vectores.

    Implementación sin dependencias externas usando math.

    Args:
        vec_a: Primer vector.
        vec_b: Segundo vector.

    Returns:
        Similitud coseno en rango [-1.0, 1.0].
        Retorna 0.0 si algún vector tiene magnitud cero.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = math.sqrt(sum(a * a for a in vec_a))
    magnitude_b = math.sqrt(sum(b * b for b in vec_b))

    if magnitude_a == 0.0 or magnitude_b == 0.0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def _format_cmx_comment(color: EDLColor, marker_type: MarkerType) -> str:
    """Formatea comentario CMX 3600 según Req 6.5.

    Formato: |C:{Color} |M:{TIPO_MARCADOR} |D:1

    Args:
        color: Color del marcador EDL.
        marker_type: Tipo de marcador.

    Returns:
        String con formato CMX 3600.
    """
    return f"|C:{color.value} |M:{marker_type.value} |D:1"


def _load_session_log(session_log: Path) -> list[dict]:
    """Carga el log de sesión desde un archivo .jsonl.

    Cada línea del archivo es un objeto JSON independiente.

    Args:
        session_log: Ruta al archivo .jsonl.

    Returns:
        Lista de diccionarios con las entradas del log.
    """
    entries: list[dict] = []

    if not session_log.exists():
        logger.warning("Archivo de log de sesión no encontrado: %s", session_log)
        return entries

    try:
        with open(session_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError as e:
        logger.error("Error leyendo log de sesión %s: %s", session_log, e)

    return entries


def _rank_segments_for_ads(
    log_entries: list[dict],
) -> list[dict]:
    """Rankea segmentos del log para sugerencias publicitarias.

    Prioriza segmentos con:
    - Alta densidad de SCRIPT_MATCH (Req 17.4)
    - Baja incidencia de anomalías vocales (Req 17.4)
    - Duración entre 15-30 segundos (Req 17.2)

    Args:
        log_entries: Entradas del log de sesión.

    Returns:
        Lista de segmentos rankeados por relevancia (máximo 3),
        cada uno con tc_in, tc_out, relevance_score, context.
    """
    if not log_entries:
        return []

    # Agrupar entradas por ventanas temporales
    # Buscar entradas con marker_type para calcular densidad
    match_entries: list[dict] = []
    anomaly_tcs: set[str] = set()

    anomaly_types = {
        "ERROR_DICCION", "CONFUSION", "REPETICION", "PANIC",
    }

    for entry in log_entries:
        marker = entry.get("marker_type", "")
        tc_str = entry.get("tc", entry.get("tc_in", ""))

        if marker == "SCRIPT_MATCH":
            match_entries.append(entry)
        elif marker in anomaly_types:
            if tc_str:
                anomaly_tcs.add(tc_str)

    if not match_entries:
        return []

    # Crear segmentos de ~20 segundos alrededor de clusters de SCRIPT_MATCH
    segments: list[dict] = []
    # Tomar hasta 3 clusters espaciados
    step = max(1, len(match_entries) // 3)

    for i in range(0, min(len(match_entries), step * 3), step):
        entry = match_entries[i]
        tc_str = entry.get("tc", entry.get("tc_in", ""))

        try:
            tc_in = SMPTETimecode.from_string(tc_str) if tc_str else None
        except ValueError:
            tc_in = None

        if tc_in is None:
            continue

        # tc_out = tc_in + ~20 segundos (600 frames a 30fps)
        tc_out = tc_in.advance_frames(600, fps=30.0)

        # Calcular relevancia: proporción de matches vs anomalías en ventana
        matches_in_window = sum(
            1 for e in match_entries
            if e.get("tc", e.get("tc_in", "")) >= tc_str
        )
        anomalies_nearby = sum(
            1 for a_tc in anomaly_tcs if a_tc >= tc_str
        )

        # Score: más matches, menos anomalías = mayor relevancia
        relevance = min(1.0, matches_in_window / max(1, len(match_entries)))
        if anomalies_nearby > 0:
            relevance *= max(0.3, 1.0 - (anomalies_nearby * 0.2))

        context_text = entry.get("detected_text", entry.get("note", ""))

        segments.append({
            "tc_in": tc_in,
            "tc_out": tc_out,
            "relevance_score": relevance,
            "context": context_text,
        })

    # Ordenar por relevancia descendente
    segments.sort(key=lambda s: s["relevance_score"], reverse=True)
    return segments[:3]
