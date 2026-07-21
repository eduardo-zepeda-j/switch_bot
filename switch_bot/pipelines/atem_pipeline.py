"""Pipeline ATEM — Control de switcher ATEM físico vía PyAtemMax.

Implementa la comunicación TCP asíncrona con el switcher ATEM,
operando en un worker thread dedicado para no bloquear la interfaz
de usuario. Proporciona actualización de tally cada 33.33 ms.

Requisitos: 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable

from switch_bot.models.config import SystemConfig
from switch_bot.models.payload import EnrichedPayload
from switch_bot.pipelines.base import Pipeline

logger = logging.getLogger(__name__)

# Tally update interval in seconds (~33.33 ms for 30 fps visual refresh)
_TALLY_INTERVAL_S = 33.33 / 1000.0


class ATEMPipeline(Pipeline):
    """Control de switcher ATEM físico vía PyAtemMax.

    Opera en un worker thread dedicado para los sockets de control
    ATEM ISO sin bloquear la interfaz de usuario.

    Attributes:
        atem_ip: Dirección IP del switcher ATEM.
        config: Configuración global del sistema.
    """

    def __init__(
        self,
        atem_ip: str,
        config: SystemConfig,
        *,
        tally_callback: Callable[[int], None] | None = None,
    ) -> None:
        """Inicializa el pipeline ATEM.

        Args:
            atem_ip: Dirección IP del switcher ATEM.
            config: Configuración global del sistema.
            tally_callback: Callback opcional para actualizar el indicador
                visual QFrame cuando cambia la fuente activa.
        """
        self._atem_ip = atem_ip
        self._config = config
        self._tally_callback = tally_callback
        self._active_source: int = 0
        self._connected: bool = False
        self._healthy: bool = False
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()

        # ATEMMax instance (created in worker thread)
        self._atem: object | None = None

        # Worker thread for ATEM socket communication
        self._worker_thread: threading.Thread | None = None
        self._tally_thread: threading.Thread | None = None

    def start(self) -> None:
        """Inicia el worker thread para conexión ATEM y el hilo de tally.

        El worker thread gestiona la conexión TCP con el switcher y
        procesa comandos sin bloquear el event loop principal.
        """
        self._shutdown_event.clear()

        self._worker_thread = threading.Thread(
            target=self._worker_run,
            name="ATEMPipeline-Worker",
            daemon=True,
        )
        self._worker_thread.start()

        self._tally_thread = threading.Thread(
            target=self._tally_loop,
            name="ATEMPipeline-Tally",
            daemon=True,
        )
        self._tally_thread.start()

        logger.info("ATEMPipeline started (worker + tally threads)")

    def stop(self) -> None:
        """Detiene los threads del pipeline ATEM de forma graceful."""
        self._shutdown_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)

        if self._tally_thread and self._tally_thread.is_alive():
            self._tally_thread.join(timeout=2.0)

        self._connected = False
        self._healthy = False
        logger.info("ATEMPipeline stopped")

    def _worker_run(self) -> None:
        """Worker thread principal: establece conexión ATEM.

        Ejecuta en un thread dedicado para no bloquear el event loop
        ni la interfaz de usuario.
        """
        try:
            # Import PyAtemMax here so it's loaded in the worker thread
            from PyAtemMax import ATEMMax  # type: ignore[import-untyped]

            self._atem = ATEMMax()
            self._atem.connect(self._atem_ip)

            # Wait for connection with timeout
            self._atem.waitForConnection(timeout=5.0)

            with self._lock:
                self._connected = True
                self._healthy = True

            logger.info(
                "ATEM connected at %s", self._atem_ip
            )

            # Keep the thread alive while not shutdown
            while not self._shutdown_event.is_set():
                self._shutdown_event.wait(timeout=1.0)

        except Exception:
            logger.exception(
                "ATEM connection failed for %s", self._atem_ip
            )
            with self._lock:
                self._connected = False
                self._healthy = False

    def _tally_loop(self) -> None:
        """Actualiza el indicador visual de tally cada ~33.33 ms.

        Ejecuta en un thread dedicado y notifica al callback registrado
        sobre la fuente activa actual.
        """
        while not self._shutdown_event.is_set():
            if self._tally_callback is not None:
                with self._lock:
                    source = self._active_source
                if source > 0:
                    try:
                        self._tally_callback(source)
                    except Exception:
                        logger.exception("Error in tally callback")

            # Sleep for approximately 33.33 ms (tally refresh interval)
            time.sleep(_TALLY_INTERVAL_S)

    async def execute(self, payload: EnrichedPayload) -> None:
        """Conmuta la entrada del mix effect block al source index.

        Delega la operación de socket al worker thread mediante
        asyncio.to_thread para no bloquear el event loop.

        Args:
            payload: Payload enriquecido con target_cam (1-4).

        Raises:
            RuntimeError: Si el pipeline no está conectado al ATEM.
        """
        if not self._connected or self._atem is None:
            raise RuntimeError(
                f"ATEM pipeline not connected to {self._atem_ip}"
            )

        source_index = payload.target_cam
        logger.debug(
            "Switching ATEM to source %d (cam %d)",
            source_index,
            payload.target_cam,
        )

        # Execute the switch command in the worker thread to avoid blocking
        await asyncio.to_thread(self._switch_source, source_index)

    def _switch_source(self, source_index: int) -> None:
        """Conmuta la fuente en el mix effect block 0.

        Ejecuta en el contexto del worker thread pool.

        Args:
            source_index: Índice de la fuente ATEM (1-based).
        """
        try:
            # ME index 0 is the main program bus
            self._atem.setProgramInputVideoSource(0, source_index)  # type: ignore[union-attr]

            with self._lock:
                self._active_source = source_index

            logger.info("ATEM switched to source %d", source_index)

        except Exception:
            logger.exception(
                "Failed to switch ATEM to source %d", source_index
            )
            with self._lock:
                self._healthy = False

    def update_tally(self, active_source: int) -> None:
        """Actualiza el indicador visual QFrame para la fuente activa.

        Registra la fuente activa y dispara el callback de tally
        inmediatamente si está configurado.

        Args:
            active_source: Índice de la fuente activa (1-based).
        """
        with self._lock:
            self._active_source = active_source

        if self._tally_callback is not None:
            try:
                self._tally_callback(active_source)
            except Exception:
                logger.exception("Error in tally callback for source %d", active_source)

    def is_healthy(self) -> bool:
        """Retorna True si el pipeline está conectado y operativo.

        Returns:
            True si la conexión ATEM está activa y el último comando
            se ejecutó sin error.
        """
        with self._lock:
            return self._healthy

    @property
    def connected(self) -> bool:
        """Retorna True si la conexión TCP al ATEM está establecida."""
        with self._lock:
            return self._connected

    @property
    def active_source(self) -> int:
        """Retorna el índice de la fuente activa actual."""
        with self._lock:
            return self._active_source
