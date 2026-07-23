"""Coordinator — Orquestador principal del sistema Switch_bot.

Conecta todos los subsistemas en un event loop asyncio:
CaptureManager → InferenceEngine → IAEnricher → DecisionEngine →
HysteresisFilter → QuadDispatcher.

Integra PanicButton con prioridad inmediata, VocalAnomalyDetector
para anomalías de audio, y SessionManager para ciclo de vida del backend.

Requisitos: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from switch_bot.capture.capture_manager import AudioPacket, CaptureManager, FramePacket
from switch_bot.engines.decision_engine import DecisionEngine
from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.engines.panic_button import PanicButton
from switch_bot.engines.script_parser import ScriptDocument
from switch_bot.engines.session_manager import SessionManager, SessionStartResult
from switch_bot.engines.vocal_anomaly_detector import (
    AudioFeatures,
    VocalAnomalyDetector,
)
from switch_bot.ia.backend_base import IABackend
from switch_bot.ia.backend_config import IABackendConfig
from switch_bot.ia.ia_enricher import IAEnricher
from switch_bot.inference.inference_engine import (
    InferenceEngine,
    InferenceMessage,
    MessageType,
)
from switch_bot.models.config import SystemConfig
from switch_bot.models.enums import MARKER_COLOR_MAP, MarkerType, SourceOrigin
from switch_bot.models.inference import CameraDecision, GazeResult, VADResult
from switch_bot.models.payload import EnrichedPayload
from switch_bot.models.timecode import SMPTETimecode
from switch_bot.pipelines.dispatcher import QuadDispatcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------


@dataclass
class ManualNote:
    """Nota manual o prompt IA inyectado desde la GUI.

    Attributes:
        text: Texto del prompt o nota.
        is_ai_prompt: True si es un prompt IA, False si es nota manual.
        timestamp: Momento de creación (time.monotonic()).
    """

    text: str
    is_ai_prompt: bool = False
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class Coordinator:
    """Orquestador principal del sistema Switch_bot.

    Ejecuta un event loop asyncio en el proceso principal (junto a PyQt6 GUI)
    que conecta todos los subsistemas:

    1. Lee resultados de InferenceEngine via multiprocessing.Queue (Req 5.1)
    2. Enruta video a inferencia y prompts/notas a pipeline EDL (Req 5.2)
    3. Mantiene aislamiento de procesos (Req 5.3)
    4. Construye EnrichedPayload (Req 16.1) y despacha a 4 pipelines (Req 16.2)
    5. Garantiza tolerancia a fallas por pipeline (Req 16.3)
    6. Completa despacho dentro de frame time (Req 16.4)

    El PanicButton se verifica con prioridad inmediata en cada iteración.
    """

    # Intervalo de polling de la queue de inferencia (segundos)
    _POLL_INTERVAL: float = 0.005  # 5ms — mantiene latencia baja

    def __init__(
        self,
        config: SystemConfig,
        script_doc: ScriptDocument,
        backend: IABackend,
        backend_config: IABackendConfig,
        dispatcher: QuadDispatcher,
        panic_button: PanicButton,
        session_log_path: Path | None = None,
    ) -> None:
        """Inicializa el Coordinator con todos los subsistemas.

        Args:
            config: Configuración global del sistema.
            script_doc: Documento de guión parseado.
            backend: Backend de IA activo.
            backend_config: Configuración del backend de IA.
            dispatcher: QuadDispatcher con los 4 pipelines registrados.
            panic_button: Instancia del PanicButton compartida con la GUI.
            session_log_path: Ruta opcional al log de sesión (.jsonl).
        """
        self._config = config
        self._script_doc = script_doc
        self._backend = backend
        self._backend_config = backend_config
        self._dispatcher = dispatcher
        self._panic_button = panic_button
        self._session_log_path = session_log_path

        # Character → Camera map del guión
        self._character_camera_map: dict[str, int] = (
            script_doc.character_camera_map
        )

        # Subsistemas internos
        self._enricher = IAEnricher(backend, script_doc)
        self._decision_engine = DecisionEngine(config, self._character_camera_map)
        self._hysteresis_filter = HysteresisFilter(
            cooldown_frames=config.hysteresis_frames, fps=config.fps
        )
        self._vocal_detector = VocalAnomalyDetector(self._enricher, script_doc)
        self._session_manager = SessionManager()

        # Queues de multiprocessing para comunicación entre procesos (Req 5.1)
        self._capture_to_inference_queue: mp.Queue = mp.Queue(maxsize=120)
        self._inference_output_queue: mp.Queue = mp.Queue(maxsize=120)

        # Queue interna para notas manuales / prompts IA desde la GUI (Req 5.2)
        self._gui_queue: asyncio.Queue[ManualNote] = asyncio.Queue()

        # Procesos e instancias
        self._capture_manager: CaptureManager | None = None
        self._inference_process: mp.Process | None = None

        # Estado del event loop
        self._running: bool = False
        self._loop_task: asyncio.Task[None] | None = None

        # Timecode: referencia de inicio de sesión para alineación TOD
        self._session_start_time: float = 0.0
        self._session_start_tc: SMPTETimecode | None = None
        self._frame_count: int = 0

        # Último estado de inferencia para el DecisionEngine
        self._last_gaze: GazeResult | None = None
        self._last_vad: VADResult | None = None

    # ------------------------------------------------------------------
    # Propiedades públicas
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True si el event loop del Coordinator está activo."""
        return self._running

    @property
    def session_manager(self) -> SessionManager:
        """Acceso al SessionManager para consultas de estado."""
        return self._session_manager

    @property
    def panic_button(self) -> PanicButton:
        """Acceso al PanicButton compartido con la GUI."""
        return self._panic_button

    @property
    def enricher(self) -> IAEnricher:
        """Acceso al IAEnricher para operaciones externas."""
        return self._enricher

    @property
    def hysteresis_filter(self) -> HysteresisFilter:
        """Acceso al filtro de histéresis."""
        return self._hysteresis_filter

    # ------------------------------------------------------------------
    # Inicio de sesión
    # ------------------------------------------------------------------

    async def start_session(self) -> SessionStartResult:
        """Inicia una sesión de grabación completa.

        Secuencia:
        1. Valida y bloquea backend via SessionManager (Req 19.4, 19.7)
        2. Vectoriza guión via IAEnricher (base RAG)
        3. Crea e inicia CaptureManager (proceso de captura)
        4. Inicia InferenceEngine como proceso dedicado (Req 5.3)
        5. Arranca el event loop principal

        Returns:
            SessionStartResult indicando éxito o fallo con info de recuperación.
        """
        if self._running:
            logger.warning("Coordinator: Ya hay una sesión activa.")
            return SessionStartResult(
                success=False,
                error_message="Ya existe una sesión activa.",
            )

        # 1. Validar backend via SessionManager
        result = await self._session_manager.start_session(
            backend=self._backend,
            config=self._backend_config,
            enricher=self._enricher,
            session_log_path=self._session_log_path,
        )

        if not result.success:
            logger.error(
                "Coordinator: Fallo al iniciar sesión — %s", result.error_message
            )
            return result

        # 2. Vectorizar guión para base RAG
        try:
            await self._enricher.vectorize_script(self._script_doc)
            logger.info("Coordinator: Guión vectorizado correctamente.")
        except Exception as e:
            logger.error("Coordinator: Error vectorizando guión: %s", e)
            await self._session_manager.end_session()
            return SessionStartResult(
                success=False,
                error_message=f"Error vectorizando guión: {e}",
                can_retry=True,
            )

        # 3. Crear e iniciar CaptureManager
        self._capture_manager = CaptureManager(
            config=self._config,
            output_queue=self._capture_to_inference_queue,
        )
        self._capture_manager.start_capture()

        # 4. Iniciar InferenceEngine como proceso dedicado (Req 5.3)
        self._inference_process = InferenceEngine.start_process(
            input_queue=self._capture_to_inference_queue,
            output_queue=self._inference_output_queue,
            config=self._config,
            character_camera_map=self._character_camera_map,
        )

        # 5. Capturar referencia temporal para alineación TOD de timecodes
        self._session_start_time = time.monotonic()
        self._session_start_tc = SMPTETimecode(
            hours=0, minutes=0, seconds=0, frames=0,
            drop_frame=self._config.drop_frame,
        )
        self._frame_count = 0

        # 6. Arrancar el event loop principal
        self._running = True
        self._loop_task = asyncio.ensure_future(self._main_loop())

        logger.info(
            "Coordinator: Sesión iniciada — fps=%.2f, cameras=%d, "
            "hysteresis=%d frames (%.1fs)",
            self._config.fps,
            self._config.num_cameras,
            self._config.hysteresis_frames,
            self._hysteresis_filter.cooldown_seconds,
        )

        return SessionStartResult(success=True)

    # ------------------------------------------------------------------
    # Detención de sesión
    # ------------------------------------------------------------------

    async def stop_session(self) -> list:
        """Detiene la sesión de grabación limpiamente.

        Secuencia:
        1. Detiene el event loop principal
        2. Detiene CaptureManager
        3. Envía STOP al InferenceEngine y espera terminación
        4. Finaliza sesión via SessionManager (genera sugerencias)

        Returns:
            Lista de AdSuggestion generadas al finalizar la sesión
            (puede estar vacía si no se pudieron generar).
        """
        if not self._running:
            logger.warning("Coordinator: No hay sesión activa para detener.")
            return []

        logger.info("Coordinator: Deteniendo sesión...")

        # 1. Detener event loop
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        # 2. Detener CaptureManager
        if self._capture_manager is not None:
            self._capture_manager.stop_capture()
            self._capture_manager = None

        # 3. Enviar STOP al InferenceEngine (Req 5.3: no bloquear captura)
        if self._inference_process is not None:
            stop_msg = InferenceMessage(msg_type=MessageType.STOP)
            try:
                self._capture_to_inference_queue.put_nowait(stop_msg)
            except Exception:
                pass  # Queue llena — el proceso terminará por timeout

            # Esperar terminación del proceso con timeout
            self._inference_process.join(timeout=5.0)
            if self._inference_process.is_alive():
                logger.warning(
                    "Coordinator: InferenceEngine no terminó en 5s — forzando."
                )
                self._inference_process.terminate()
            self._inference_process = None

        # 4. Finalizar sesión via SessionManager (genera sugerencias publicitarias)
        suggestions = await self._session_manager.end_session(
            script_doc=self._script_doc
        )

        # Limpiar estado
        self._last_gaze = None
        self._last_vad = None
        self._frame_count = 0
        self._hysteresis_filter.reset()

        logger.info("Coordinator: Sesión detenida correctamente.")

        return suggestions

    # ------------------------------------------------------------------
    # Inyección de notas/prompts desde GUI (Req 5.2)
    # ------------------------------------------------------------------

    def submit_manual_note(self, text: str) -> None:
        """Inyecta una nota manual desde la GUI al pipeline EDL.

        Enrutamiento independiente del flujo de video (Req 5.2).

        Args:
            text: Texto de la nota manual del operador.
        """
        note = ManualNote(text=text, is_ai_prompt=False, timestamp=time.monotonic())
        try:
            self._gui_queue.put_nowait(note)
        except asyncio.QueueFull:
            logger.warning("Coordinator: GUI queue llena — nota descartada.")

    def submit_ai_prompt(self, prompt: str) -> None:
        """Inyecta un prompt IA desde la GUI para procesamiento por IAEnricher.

        Enrutamiento independiente del flujo de video (Req 5.2).

        Args:
            prompt: Texto del prompt IA del operador.
        """
        note = ManualNote(text=prompt, is_ai_prompt=True, timestamp=time.monotonic())
        try:
            self._gui_queue.put_nowait(note)
        except asyncio.QueueFull:
            logger.warning("Coordinator: GUI queue llena — prompt descartado.")

    # ------------------------------------------------------------------
    # Event Loop principal
    # ------------------------------------------------------------------

    async def _main_loop(self) -> None:
        """Event loop principal del Coordinator.

        Ciclo continuo que:
        1. Verifica PanicButton con prioridad inmediata
        2. Consume resultados de InferenceEngine (GazeResult/VADResult)
        3. Procesa notas/prompts de la GUI
        4. Ejecuta pipeline: DecisionEngine → HysteresisFilter → QuadDispatcher
        5. Avanza el frame counter de histéresis

        El polling de multiprocessing.Queue es no-bloqueante usando
        asyncio.to_thread para no congelar el event loop (Req 5.1).
        """
        logger.info("Coordinator: Event loop principal iniciado.")

        while self._running:
            try:
                # Prioridad 1: Verificar PanicButton (sub-frame response)
                if self._panic_button.is_active:
                    # Cuando panic está activo, no procesamos decisiones automáticas
                    await asyncio.sleep(self._POLL_INTERVAL)
                    continue

                # Prioridad 2: Consumir resultados de inferencia (no-bloqueante)
                inference_result = await self._poll_inference_queue()

                if inference_result is not None:
                    await self._process_inference_result(inference_result)

                # Prioridad 3: Procesar notas/prompts de la GUI
                await self._process_gui_queue()

                # Avanzar frame counter de histéresis
                self._hysteresis_filter.tick()
                self._frame_count += 1

                # Yield al event loop para mantener responsividad
                await asyncio.sleep(self._POLL_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Coordinator: Error en main loop: %s", e, exc_info=True)
                await asyncio.sleep(self._POLL_INTERVAL)

        logger.info("Coordinator: Event loop principal detenido.")

    # ------------------------------------------------------------------
    # Polling de queue de inferencia
    # ------------------------------------------------------------------

    async def _poll_inference_queue(self) -> GazeResult | VADResult | None:
        """Lee un resultado de la queue de inferencia sin bloquear.

        Usa asyncio.to_thread para que el get_nowait no bloquee
        el event loop asyncio (Req 5.1).

        Returns:
            GazeResult o VADResult si hay datos disponibles, None si la queue
            está vacía.
        """
        try:
            result = await asyncio.to_thread(
                self._try_get_from_queue, self._inference_output_queue
            )
            return result
        except Exception:
            return None

    @staticmethod
    def _try_get_from_queue(queue: mp.Queue) -> Any | None:
        """Intenta leer de una multiprocessing.Queue sin bloquear.

        Args:
            queue: Queue a leer.

        Returns:
            El item leído o None si la queue está vacía.
        """
        try:
            return queue.get_nowait()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Procesamiento de resultados de inferencia
    # ------------------------------------------------------------------

    async def _process_inference_result(
        self, result: GazeResult | VADResult
    ) -> None:
        """Procesa un resultado de inferencia y ejecuta el pipeline de decisión.

        Almacena el último GazeResult y VADResult. Cuando ambos están
        disponibles, ejecuta:
        DecisionEngine → HysteresisFilter → EnrichedPayload → QuadDispatcher

        Args:
            result: Resultado de inferencia (GazeResult o VADResult).
        """
        if isinstance(result, GazeResult):
            self._last_gaze = result
        elif isinstance(result, VADResult):
            self._last_vad = result

            # Procesar anomalías vocales si hay datos de audio
            if result.is_speaking and result.speaker_id:
                await self._check_vocal_anomalies(result)

        # Ejecutar decisión solo si tenemos ambos resultados
        if self._last_gaze is None or self._last_vad is None:
            return

        # DecisionEngine evalúa gaze + VAD
        decision = self._decision_engine.evaluate(self._last_gaze, self._last_vad)

        if decision is None:
            return

        # HysteresisFilter valida cooldown
        if not self._hysteresis_filter.should_allow_switch(decision):
            return

        # Construir y despachar EnrichedPayload
        await self._dispatch_decision(decision)

    # ------------------------------------------------------------------
    # Despacho de decisiones (Req 16.1, 16.2, 16.3, 16.4)
    # ------------------------------------------------------------------

    async def _dispatch_decision(self, decision: CameraDecision) -> None:
        """Construye EnrichedPayload y despacha a los 4 pipelines.

        Construye el payload enriquecido (Req 16.1) y lo despacha
        simultáneamente a ATEM, OBS, Metadata y EDL (Req 16.2).
        La falla de un pipeline no bloquea los demás (Req 16.3).
        El despacho debe completarse dentro de frame time (Req 16.4).

        Args:
            decision: Decisión de cámara aprobada por el filtro de histéresis.
        """
        # Resolver personaje asociado a la cámara destino
        personaje = self._resolve_character(decision.target_cam)

        # Determinar tipo de marcador y color según el origen
        marker_type = self._resolve_marker_type(decision)
        color = MARKER_COLOR_MAP.get(marker_type, MARKER_COLOR_MAP[MarkerType.ENTRADA])

        # Calcular timecode actual
        tc_in = self._current_timecode()

        # Construir EnrichedPayload (Req 16.1)
        payload = EnrichedPayload(
            personaje=personaje,
            target_cam=decision.target_cam,
            marker_type=marker_type,
            note=decision.reason,
            tc_in=tc_in,
            source_origin=decision.source_origin,
            color=color,
        )

        # Despachar a 4 pipelines simultáneamente (Req 16.2, 16.3, 16.4)
        dispatch_result = await self._dispatcher.dispatch(payload)

        if dispatch_result.failures > 0:
            logger.warning(
                "Coordinator: Despacho con %d/%d fallas: %s",
                dispatch_result.failures,
                dispatch_result.total,
                [str(e) for e in dispatch_result.errors],
            )

    # ------------------------------------------------------------------
    # Anomalías vocales
    # ------------------------------------------------------------------

    async def _check_vocal_anomalies(self, vad_result: VADResult) -> None:
        """Ejecuta VocalAnomalyDetector sobre el audio transcrito.

        Las anomalías generan marcadores que bypasean la histéresis
        (SourceOrigin.ANOMALY).

        Args:
            vad_result: Resultado de VAD con actividad vocal detectada.
        """
        # Construir AudioFeatures básicas desde el VAD
        # En producción, esto vendría de un análisis más completo del audio
        audio_features = AudioFeatures(
            energy_level=vad_result.confidence,
            has_silence_gap=False,
            duration_ms=int(1000 / self._config.fps),  # Duración de un frame
            pitch_variance=0.0,
        )

        # Usar speaker_id como transcript placeholder
        # En producción vendría de un ASR (speech-to-text)
        transcript = vad_result.speaker_id or ""

        if not transcript:
            return

        try:
            anomalies = await self._vocal_detector.analyze_segment(
                transcript=transcript,
                audio_features=audio_features,
            )
        except Exception as e:
            logger.error("Coordinator: Error en VocalAnomalyDetector: %s", e)
            return

        # Despachar cada anomalía detectada
        for anomaly in anomalies:
            tc_in = self._current_timecode()
            personaje = self._resolve_character_from_speaker(
                vad_result.speaker_id
            )

            payload = EnrichedPayload(
                personaje=personaje,
                target_cam=self._character_camera_map.get(
                    vad_result.speaker_id or "", 1
                ),
                marker_type=anomaly.anomaly_type,
                note=anomaly.description,
                tc_in=tc_in,
                source_origin=anomaly.source_origin,
                color=anomaly.color,
            )

            # Anomalías bypasean histéresis — despachar directamente
            dispatch_result = await self._dispatcher.dispatch(payload)

            if dispatch_result.failures > 0:
                logger.warning(
                    "Coordinator: Despacho anomalía con %d fallas.",
                    dispatch_result.failures,
                )

    # ------------------------------------------------------------------
    # Procesamiento de GUI queue (notas manuales y prompts IA)
    # ------------------------------------------------------------------

    async def _process_gui_queue(self) -> None:
        """Procesa notas manuales y prompts IA pendientes de la GUI.

        Los prompts IA se procesan via IAEnricher.process_manual_prompt().
        Las notas manuales se despachan directamente como marcadores.
        Ambos se enrutan independientemente del flujo de video (Req 5.2).
        """
        while not self._gui_queue.empty():
            try:
                note = self._gui_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            tc_in = self._current_timecode()

            if note.is_ai_prompt:
                await self._handle_ai_prompt(note.text, tc_in)
            else:
                await self._handle_manual_note(note.text, tc_in)

    async def _handle_ai_prompt(self, prompt: str, tc: SMPTETimecode) -> None:
        """Procesa un prompt IA via IAEnricher y despacha el marcador.

        Args:
            prompt: Texto del prompt del operador.
            tc: Timecode SMPTE del momento del prompt.
        """
        try:
            marker_event = await self._enricher.process_manual_prompt(prompt, tc)
        except Exception as e:
            logger.error("Coordinator: Error procesando prompt IA: %s", e)
            return

        # Construir EnrichedPayload desde MarkerEvent
        payload = EnrichedPayload(
            personaje="OPERADOR",
            target_cam=1,  # Cam por defecto para prompts IA
            marker_type=marker_event.marker_type,
            note=marker_event.note,
            tc_in=tc,
            source_origin=marker_event.source_origin,
            color=marker_event.color,
        )

        # Forzar bypass de histéresis para marcadores IA
        self._hysteresis_filter.force_allow()

        await self._dispatcher.dispatch(payload)

    async def _handle_manual_note(self, text: str, tc: SMPTETimecode) -> None:
        """Despacha una nota manual como marcador MANUAL_NOTE.

        Args:
            text: Texto de la nota manual.
            tc: Timecode SMPTE del momento de la nota.
        """
        color = MARKER_COLOR_MAP.get(MarkerType.MANUAL_NOTE, MARKER_COLOR_MAP[MarkerType.MANUAL_NOTE])

        payload = EnrichedPayload(
            personaje="OPERADOR",
            target_cam=1,  # Cam por defecto para notas manuales
            marker_type=MarkerType.MANUAL_NOTE,
            note=text,
            tc_in=tc,
            source_origin=SourceOrigin.MANUAL,
            color=color,
        )

        # Forzar bypass de histéresis para marcadores manuales
        self._hysteresis_filter.force_allow()

        await self._dispatcher.dispatch(payload)

    # ------------------------------------------------------------------
    # Utilidades de timecode
    # ------------------------------------------------------------------

    def _current_timecode(self) -> SMPTETimecode:
        """Calcula el timecode SMPTE actual basado en frame count.

        Usa alineación TOD: captura el reloj real al inicio de sesión
        y avanza por frame count desde ahí.

        Returns:
            SMPTETimecode del frame actual.
        """
        if self._session_start_tc is None:
            # Fallback: timecode cero
            return SMPTETimecode(
                hours=0, minutes=0, seconds=0, frames=0,
                drop_frame=self._config.drop_frame,
            )

        return self._session_start_tc.advance_frames(
            self._frame_count, fps=self._config.fps
        )

    # ------------------------------------------------------------------
    # Resolución de personaje
    # ------------------------------------------------------------------

    def _resolve_character(self, target_cam: int) -> str:
        """Resuelve el nombre del personaje asociado a una cámara.

        Args:
            target_cam: Índice de cámara (1-4).

        Returns:
            Nombre del personaje o "CAM_{N}" si no hay mapeo.
        """
        for character, cam in self._character_camera_map.items():
            if cam == target_cam:
                return character
        return f"CAM_{target_cam}"

    def _resolve_character_from_speaker(self, speaker_id: str | None) -> str:
        """Resuelve personaje desde speaker_id de VAD.

        Args:
            speaker_id: Identificador del hablante.

        Returns:
            Nombre del personaje o "DESCONOCIDO" si no hay mapeo.
        """
        if speaker_id and speaker_id in self._character_camera_map:
            return speaker_id
        return "DESCONOCIDO"

    # ------------------------------------------------------------------
    # Resolución de tipo de marcador
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_marker_type(decision: CameraDecision) -> MarkerType:
        """Determina el MarkerType según la razón de la decisión.

        Args:
            decision: Decisión de cámara.

        Returns:
            MarkerType apropiado para la decisión.
        """
        reason = decision.reason.upper()

        if "REACTION" in reason:
            return MarkerType.IMAGEN
        elif "SPEAKER" in reason:
            return MarkerType.ENTRADA
        elif decision.source_origin == SourceOrigin.AI:
            return MarkerType.AI_PROMPT
        elif decision.source_origin == SourceOrigin.MANUAL:
            return MarkerType.MANUAL_NOTE
        elif decision.source_origin == SourceOrigin.ANOMALY:
            return MarkerType.TOS  # Default anomaly marker
        else:
            return MarkerType.ENTRADA
