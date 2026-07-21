---
inclusion: auto
---

# Directrices de Rendimiento — Switch_bot

## Restricción Fundamental: Frame Time Budget

El sistema tiene un presupuesto estricto de **33.33 ms por frame** (a 30 fps). Toda la cadena de procesamiento debe completarse dentro de este tiempo. Las reglas de rendimiento derivan de esta restricción.

## Aislamiento de Procesos (multiprocessing)

- La captura de video NUNCA debe bloquearse por operaciones de inferencia, red o escritura a disco.
- Usar `multiprocessing.Queue` con `put_nowait()` cuando sea posible para evitar bloqueos en el productor.
- Cada proceso (captura, inferencia, pipelines) debe tener su propio event loop o bucle dedicado.
- Medir el tiempo de procesamiento de cada frame con `time.perf_counter_ns()` y alertar si se excede el 80% del frame time.

## Llamadas a Backends de IA (Bedrock y Local)

- Las llamadas a backends de IA son inherentemente lentas (100ms–5s) — NUNCA deben ejecutarse en el hot path del frame loop.
- Usar `asyncio.create_task()` para delegar enriquecimiento semántico sin bloquear el procesamiento de frames.
- Implementar un buffer de segmentos pendientes: si el backend está lento, encolar segmentos y procesarlos cuando haya capacidad.
- Establecer timeouts estrictos:
  - Embeddings: 5 segundos máximo por batch.
  - Análisis contextual (LLM): 10 segundos máximo por segmento.
  - Prompts manuales: 10 segundos (Requisito 6.4).
- Si un segmento excede el timeout, descartarlo (log + continuar) — NO reintentar en el hot path.

## Modelos Locales (Ollama/llama.cpp)

- Los modelos locales tienen latencia variable según hardware. Preferir modelos cuantizados (Q4_K_M, Q5_K_M) para mantener latencia predecible.
- Para embeddings locales, usar batching: acumular textos y generar embeddings en lotes de 8-16 textos.
- Verificar que el modelo está cargado en VRAM antes de iniciar la sesión (la primera inferencia de Ollama es lenta por carga).
- Implementar warm-up: hacer una inferencia dummy al inicializar el backend para pre-cargar el modelo.

## Escritura a Disco (.edl, .drp, .jsonl)

- Usar modo append (`'a'`) con `flush()` atómico — nunca reescribir archivos completos en cada evento.
- Bufferizar escrituras EDL/DRP con un buffer de hasta 10 eventos antes de hacer flush, excepto para marcadores PANIC (flush inmediato).
- Las operaciones de disco deben ejecutarse en un thread dedicado (no en el event loop de asyncio) usando `asyncio.to_thread()`.
- Considerar `os.fsync(fd)` solo en checkpoints, no en cada escritura individual.

## PyQt6 GUI

- El thread de GUI NUNCA debe ejecutar operaciones bloqueantes (red, disco, inferencia).
- Comunicar entre el Coordinator y la GUI usando `QMetaObject.invokeMethod()` con `Qt.QueuedConnection` o signals/slots.
- Actualizar indicadores de tally cada 33.33 ms usando un `QTimer` — no más frecuente.
- Las operaciones de listado de modelos (descubrimiento) deben ejecutarse en un `QThread` separado con señal de progreso.

## Comunicación TCP/WebSocket (ATEM, OBS)

- Los sockets ATEM deben operarse en un thread dedicado con su propio selector/event loop.
- Las reconexiones WebSocket OBS deben usar backoff exponencial (1s, 2s, 4s) para no saturar la red.
- Implementar heartbeat checks periódicos (cada 5s) para detectar desconexiones silenciosas.
- Usar `TCP_NODELAY` para los sockets ATEM para minimizar latencia de comandos de conmutación.

## MediaPipe y VAD

- MediaPipe gaze tracking debe procesar un frame a la vez — NO acumular frames sin procesar.
- Si la inferencia excede el frame time, descartar el frame actual y procesar el siguiente (skip frame strategy).
- Preallocar buffers numpy para frames de video: evitar asignaciones de memoria en el hot loop.
- VAD debe operar sobre chunks de 20-30 ms — alinear con el frame time para procesamiento sincronizado.

## Memory Management

- Los vectores de embeddings del guión se almacenan en un numpy array contiguous para búsquedas rápidas (cosine similarity vectorizada).
- Liberar explícitamente vectores grandes al finalizar la sesión (`del` + `gc.collect()`).
- Monitorear uso de memoria RSS del proceso principal — alertar si supera 2 GB.
- Las Queues de multiprocessing deben tener maxsize configurado (e.g., 30 frames) para prevenir acumulación unbounded si un consumidor se atrasa.

## Profiling y Métricas

- Instrumentar el hot loop con contadores de tiempo para cada etapa: captura → inferencia → decisión → dispatch.
- Mantener un rolling average de frame time — si el P95 excede 30ms, reducir carga (skip frames, reducir calidad de inferencia).
- Loguear métricas de rendimiento cada 30 segundos en el log de sesión (sin afectar el frame time).
