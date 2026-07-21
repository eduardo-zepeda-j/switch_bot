# Implementation Plan: Switch_bot

## Overview

Implementación incremental del sistema Switch_bot — un orquestador de producción multicámara en tiempo real con inferencia visual, análisis semántico vía IA multi-backend (AWS Bedrock o modelos locales Ollama/llama.cpp), y ejecución cuádruple paralela de pipelines. El componente de enriquecimiento semántico (IAEnricher) abstrae el backend de IA mediante un patrón Strategy, permitiendo al operador elegir entre cloud y local. Se construye desde los modelos de datos fundamentales hasta la integración final del sistema completo.

## Tasks

- [x] 1. Estructura del proyecto y modelos de datos fundamentales
  - [x] 1.1 Crear la estructura de directorios del proyecto y configurar dependencias
    - Crear `pyproject.toml` con dependencias: mediapipe, pyatemmax, boto3, pyqt6, obs-websocket-py, hypothesis, pytest, httpx, aiohttp
    - Crear estructura: `switch_bot/`, `switch_bot/models/`, `switch_bot/serializers/`, `switch_bot/engines/`, `switch_bot/pipelines/`, `switch_bot/capture/`, `switch_bot/inference/`, `switch_bot/gui/`, `switch_bot/ia/`, `tests/unit/`, `tests/property/`, `tests/integration/`
    - Crear `conftest.py` con configuración de Hypothesis (max_examples=100 dev, 200 CI)
    - _Requisitos: 5.1, 5.3_

  - [x] 1.2 Implementar SMPTETimecode con aritmética de frames y Drop Frame
    - Crear `switch_bot/models/timecode.py` con dataclass frozen `SMPTETimecode`
    - Implementar `to_string()` con separador `;` para drop frame y `:` para non-drop frame
    - Implementar `from_string()` para parsear timecodes SMPTE
    - Implementar `advance_frames()` con lógica Drop Frame SMPTE 12M (skip frames 0,1 excepto cada 10 min)
    - Implementar métodos auxiliares `_to_frame_count()` y `_from_frame_count()`
    - _Requisitos: 12.5, 18.3, 18.4_

  - [x] 1.3 Test de propiedad: separador Drop Frame vs Non-Drop Frame
    - **Property 7: Separador de timecode Drop Frame vs. Non-Drop Frame**
    - **Valida: Requisitos 12.5, 18.3**

  - [x] 1.4 Implementar enums MarkerType, EDLColor, SourceOrigin y el mapeo MARKER_COLOR_MAP
    - Crear `switch_bot/models/enums.py` con `MarkerType`, `EDLColor`, `SourceOrigin`
    - Definir `MARKER_COLOR_MAP` según la especificación del diseño
    - _Requisitos: 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 13.3_

  - [x] 1.5 Implementar SystemConfig con cálculos de frame_time y cooldown
    - Crear `switch_bot/models/config.py` con dataclass `SystemConfig`
    - Implementar propiedad `cooldown_seconds` y validación de fps soportados (60, 30, 29.97)
    - Establecer valores por defecto: 1080p29.97, 90 frames de histéresis
    - Incluir campo `ia_backend_config: IABackendConfig | None` para referencia al backend IA activo
    - _Requisitos: 18.1, 18.2, 18.3, 19.6_

  - [x] 1.6 Test de propiedad: cálculo correcto de frame_time y cooldown a partir de fps
    - **Property 12: Cálculo correcto de frame_time y cooldown a partir de fps**
    - **Valida: Requisitos 18.3**

  - [x] 1.7 Implementar EnrichedPayload y modelos auxiliares (GazeResult, VADResult, CameraDecision)
    - Crear `switch_bot/models/payload.py` con dataclass frozen `EnrichedPayload`
    - Crear `switch_bot/models/inference.py` con `GazeResult`, `VADResult`, `CameraDecision`
    - _Requisitos: 16.1_

  - [x] 1.8 Test de propiedad: el Payload Enriquecido contiene todos los campos requeridos
    - **Property 10: El Payload Enriquecido contiene todos los campos requeridos**
    - **Valida: Requisitos 16.1**

- [x] 2. Serializadores EDL y DRP
  - [x] 2.1 Implementar EDLEvent y EDLDocument con serialización CMX 3600
    - Crear `switch_bot/serializers/edl_serializer.py`
    - Implementar `EDLEvent.to_cmx3600()` con formato: `NNN  001      V     C        TC_IN TC_OUT TC_IN TC_OUT` + comentario `|C:{color} |M:{tipo} |D:1`
    - Implementar `EDLEvent.from_cmx3600()` para parseo bidireccional
    - Implementar `EDLDocument.serialize()` con cabecera TITLE + FCM
    - Implementar `EDLDocument.parse()` para reconstrucción desde texto
    - Implementar `EDLDocument.add_event()` con auto-numeración secuencial
    - Cada evento: tc_out = tc_in + 1 frame, numeración 001..N
    - _Requisitos: 13.1, 13.4, 13.5, 13.6, 15.1, 15.2, 15.3, 15.4_

  - [x] 2.2 Test de propiedad: round-trip de serialización EDL
    - **Property 2: Round-trip de serialización EDL**
    - **Valida: Requisitos 15.1, 15.2, 15.3, 15.4**

  - [x] 2.3 Test de propiedad: eventos EDL de 1 frame con numeración secuencial
    - **Property 6: Eventos EDL son de 1 frame con numeración secuencial**
    - **Valida: Requisitos 13.4, 13.6**

  - [x] 2.4 Test de propiedad: mapeo MarkerType → EDLColor
    - **Property 5: Mapeo correcto de MarkerType a EDLColor en serialización CMX 3600**
    - **Valida: Requisitos 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 13.3**

  - [x] 2.5 Implementar DRPDocument con serialización JSON Lines
    - Crear `switch_bot/serializers/drp_serializer.py`
    - Implementar dataclasses: `DRPSource`, `DRPMixEffectBlock`, `DRPProjectConfig`, `DRPSwitchEvent`
    - Implementar `DRPDocument.serialize()`: primera línea = config JSON, líneas siguientes = eventos JSON
    - Implementar `DRPDocument.parse()` para reconstrucción desde JSON Lines
    - Implementar `DRPDocument.add_switch_event()` con timecode y source
    - _Requisitos: 12.1, 12.2, 12.3, 12.4, 12.5, 14.1, 14.2, 14.3, 14.4_

  - [x] 2.6 Test de propiedad: round-trip de serialización DRP
    - **Property 1: Round-trip de serialización DRP**
    - **Valida: Requisitos 14.1, 14.2, 14.3, 14.4**

- [x] 3. Checkpoint — Verificar modelos y serializadores
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

- [x] 4. Script Parser y Motor de Decisión
  - [x] 4.1 Implementar ScriptParser con soporte PDF/MD/JSON
    - Crear `switch_bot/engines/script_parser.py`
    - Implementar dataclasses `ScriptBlock` y `ScriptDocument`
    - Implementar `ScriptParser.load()` con detección de formato (PDF via PyMuPDF/pdfplumber, MD via parsing de texto, JSON directo)
    - Implementar `ScriptParser.get_block()` y `get_character_mapping()`
    - Lanzar `ScriptFormatError` con mensaje descriptivo si el formato es inválido
    - _Requisitos: 3.1, 3.2, 3.3, 3.4_

  - [x] 4.2 Test de propiedad: documentos con formato inválido generan error descriptivo
    - **Property 14: Documentos de guión con formato inválido generan error descriptivo**
    - **Valida: Requisitos 3.4**

  - [x] 4.3 Implementar DecisionEngine con lógica de evaluación
    - Crear `switch_bot/engines/decision_engine.py`
    - Implementar prioridad: habla activa → cámara hablante; mirada a otro → reacción; sin habla → no cambio
    - Usar character_camera_map del guión para resolver personaje → cámara
    - _Requisitos: 8.1, 2.4_

  - [x] 4.4 Implementar HysteresisFilter con cooldown de 90 frames
    - Crear `switch_bot/engines/hysteresis_filter.py`
    - Implementar `should_allow_switch()` con cooldown configurable (90 frames = 3s a 30fps)
    - Implementar `force_allow()` para bypass de marcadores manuales/IA/anomalías
    - Implementar propiedad `is_cooling_down`
    - _Requisitos: 8.2, 8.3, 8.4_

  - [x] 4.5 Test de propiedad: histéresis bloquea conmutaciones automáticas dentro del cooldown
    - **Property 3: El filtro de histéresis bloquea conmutaciones automáticas dentro del cooldown**
    - **Valida: Requisitos 8.2, 8.4**

  - [x] 4.6 Test de propiedad: marcadores manuales/IA/anomalías bypasean histéresis
    - **Property 4: Marcadores manuales, de IA y de anomalías vocales bypasean el filtro**
    - **Valida: Requisitos 4.4, 7.6, 8.3**

  - [x] 4.7 Implementar PanicButton con override inmediato
    - Crear `switch_bot/engines/panic_button.py`
    - Implementar `activate()`: pausa toda automatización + registra bandera EDL con SMPTE_TC
    - Implementar `deactivate()`: restaura operación automática
    - Implementar propiedad `is_active`
    - Garantizar respuesta < 1 frame time (33.33 ms)
    - _Requisitos: 9.1, 9.2, 9.3, 9.4_

  - [x] 4.8 Test de propiedad: Panic Button pausa y restaura la automatización
    - **Property 8: El Panic Button pausa y restaura la automatización**
    - **Valida: Requisitos 9.1, 9.3**

- [x] 5. Checkpoint — Verificar motores de decisión
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

- [x] 6. Pipelines de ejecución
  - [x] 6.1 Implementar interfaz base Pipeline y QuadDispatcher
    - Crear `switch_bot/pipelines/base.py` con interfaz abstracta `Pipeline` (execute, is_healthy)
    - Crear `switch_bot/pipelines/dispatcher.py` con `QuadDispatcher`
    - Implementar dispatch paralelo con `asyncio.gather(*tasks, return_exceptions=True)`
    - Implementar `DispatchResult` con conteo de éxitos/fallas
    - _Requisitos: 16.2, 16.3, 16.4_

  - [x] 6.2 Test de propiedad: payload se despacha a todos los pipelines con tolerancia a fallas
    - **Property 9: El Payload Enriquecido se despacha a todos los pipelines con tolerancia a fallas**
    - **Valida: Requisitos 16.2, 16.3**

  - [x] 6.3 Implementar Pipeline ATEM (PyAtemMax TCP async)
    - Crear `switch_bot/pipelines/atem_pipeline.py`
    - Implementar conexión TCP asíncrona al switcher ATEM
    - Implementar `execute()`: conmutar entrada del mix effect block al source index
    - Implementar `update_tally()`: actualizar indicador visual QFrame cada 33.33 ms
    - Worker thread dedicado para sockets ATEM
    - _Requisitos: 10.1, 10.2, 10.3, 10.4_

  - [x] 6.4 Implementar Pipeline OBS (WebSocket/MCP)
    - Crear `switch_bot/pipelines/obs_pipeline.py`
    - Implementar conexión WebSocket a OBS Studio
    - Implementar `execute()`: cambiar escena OBS al personaje/encuadre
    - Implementar `reconnect()`: reconexión asíncrona automática con backoff exponencial
    - Sincronizar estado al reconectar
    - _Requisitos: 11.1, 11.2, 11.3, 11.4_

  - [x] 6.5 Implementar Pipeline Metadata (.jsonl + .drp)
    - Crear `switch_bot/pipelines/metadata_pipeline.py`
    - Implementar `execute()`: preparar datos en memoria y delegar escritura a thread pool via `asyncio.to_thread()`
    - Integrar `DRPDocument` para compilar líneas en el .drp en tiempo real
    - Escritura atómica non-blocking con flush + fsync en thread dedicado para no bloquear el event loop
    - _Requisitos: 12.1, 12.2, 12.3, 12.4_

  - [x] 6.6 Implementar Pipeline EDL (Motor CMX 3600)
    - Crear `switch_bot/pipelines/edl_pipeline.py`
    - Implementar `execute()`: serializar evento CMX 3600 en memoria y delegar escritura a thread pool via `asyncio.to_thread()`
    - Integrar `EDLDocument` para escritura en tiempo real
    - Implementar clasificación de notas: Manual vs IA/Contexto
    - Escritura atómica non-blocking con flush + fsync en thread dedicado para no bloquear el event loop
    - _Requisitos: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [x] 7. Checkpoint — Verificar pipelines
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

- [ ] 8. Backend de IA multi-proveedor (Patrón Strategy)
  - [ ] 8.1 Implementar IABackendConfig con persistencia JSON
    - Crear `switch_bot/ia/__init__.py`
    - Crear `switch_bot/ia/backend_config.py` con dataclass `IABackendConfig`
    - Implementar campos: backend_type, embedding_model_id, llm_model_id, aws_region, aws_profile, local_runtime, local_base_url, gguf_model_dir, timeouts
    - Implementar `to_json()` y `from_json()` para serialización/deserialización
    - Implementar `default_bedrock()` y `default_local()` como factories
    - Implementar persistencia en `~/.switch_bot/config.json` (lectura/escritura)
    - _Requisitos: 19.6, 19.1_

  - [ ] 8.2 Test de propiedad: round-trip de persistencia de IABackendConfig
    - **Property 15: Round-trip de persistencia de IABackendConfig**
    - **Valida: Requisitos 19.6**

  - [ ] 8.3 Implementar IAModelInfo e IAModelCatalog
    - Crear `switch_bot/ia/model_catalog.py`
    - Implementar dataclass `IAModelInfo`: model_id, name, model_type ("embedding"/"llm"), size_bytes, context_window, description
    - Implementar dataclass `IAModelCatalog`: backend_type, embedding_models, llm_models, last_updated
    - Implementar `get_embedding_model_ids()` y `get_llm_model_ids()`
    - _Requisitos: 19.2, 19.3_

  - [ ] 8.4 Implementar interfaz abstracta IABackend (ABC)
    - Crear `switch_bot/ia/backend_base.py` con clase abstracta `IABackend`
    - Definir métodos abstractos: initialize(), validate_connection(timeout), list_available_models(), generate_embeddings(texts), analyze_context(prompt, context), compute_similarity(text_a, text_b)
    - Definir propiedades abstractas: backend_type, is_connected
    - Implementar excepciones: `BackendConnectionError`, `BackendTimeoutError`, `ModelDiscoveryError`
    - _Requisitos: 19.4, 19.5, 19.8, 19.9_

  - [ ] 8.5 Implementar BedrockBackend (AWS Bedrock — Titan Embeddings V2 + Claude 3.5)
    - Crear `switch_bot/ia/bedrock_backend.py` con clase `BedrockBackend(IABackend)`
    - Implementar `initialize()`: crear cliente boto3 con credenciales AWS
    - Implementar `validate_connection(timeout)`: health check con timeout de 10s
    - Implementar `list_available_models()`: listar modelos disponibles en cuenta AWS Bedrock
    - Implementar `generate_embeddings()`: embeddings vía Titan Embeddings V2
    - Implementar `analyze_context()`: análisis contextual vía Claude 3.5 Sonnet/Haiku
    - Implementar `compute_similarity()`: cosine similarity sobre embeddings Titan
    - Implementar retry con backoff exponencial (max 3 reintentos) para timeout/throttle
    - _Requisitos: 6.6, 19.2, 19.4, 19.5_

  - [ ] 8.6 Implementar LocalBackend (Ollama / llama.cpp / GGUF)
    - Crear `switch_bot/ia/local_backend.py` con clase `LocalBackend(IABackend)`
    - Implementar `initialize()`: verificar que runtime local (Ollama/llama.cpp) esté activo
    - Implementar `validate_connection(timeout)`: verificar accesibilidad del runtime local
    - Implementar `list_available_models()`: GET /api/tags (Ollama) o escaneo de directorio GGUF (llama.cpp)
    - Implementar `generate_embeddings()`: embeddings vía modelo local (nomic-embed-text, etc.)
    - Implementar `analyze_context()`: análisis contextual vía LLM local (llama3, mistral, etc.)
    - Implementar `compute_similarity()`: cosine similarity sobre embeddings locales
    - Manejar errores: runtime no iniciado, modelo no encontrado, out of memory
    - _Requisitos: 6.7, 19.3, 19.4, 19.5, 19.9_

  - [ ] 8.7 Implementar EnrichmentResult (resultado normalizado)
    - Crear `switch_bot/ia/enrichment_result.py` con dataclass `EnrichmentResult`
    - Campos: similarity_score [0.0, 1.0], is_deviation (bool), detected_text, expected_text, marker_type, color, metadata
    - Garantizar estructura idéntica independientemente del backend activo
    - _Requisitos: 6.2, 6.3, 19.8_

  - [ ] 8.8 Implementar IAEnricher (orquestador agnóstico al backend — Strategy Pattern)
    - Crear `switch_bot/ia/ia_enricher.py` con clase `IAEnricher`
    - Constructor recibe `IABackend` (interfaz abstracta) + `ScriptDocument`
    - Implementar `vectorize_script()`: genera embeddings del guión completo usando backend activo como base RAG
    - Implementar `compare_live_audio()`: compara transcripción vs guión, retorna EnrichmentResult con score [0.0, 1.0]; si score < 0.7 genera marcador SCRIPT_DEVIATION con metadatos
    - Implementar `process_manual_prompt()`: procesa prompt del operador con timeout 10s → marcador AI_PROMPT color Magenta
    - Implementar `generate_ad_suggestions()`: analiza log de sesión + guión → 3 AdSuggestion con tc_in < tc_out, duración 15-30s
    - Implementar manejo de errores de backend: log con SMPTE_TC + continuar sin detener sesión
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.8, 17.1, 17.2, 17.3, 17.4_

  - [ ] 8.9 Test de propiedad: score de similitud semántica acotado entre 0.0 y 1.0
    - **Property 18: Score de similitud semántica está acotado entre 0.0 y 1.0**
    - **Valida: Requisitos 6.2**

  - [ ] 8.10 Test de propiedad: umbral de similitud genera marcadores de desviación correctamente
    - **Property 19: Umbral de similitud genera marcadores de desviación correctamente**
    - **Valida: Requisitos 6.3**

  - [ ] 8.11 Test de propiedad: consistencia de estructura de salida entre backends
    - **Property 17: Consistencia de estructura de salida entre backends**
    - **Valida: Requisitos 19.8**

  - [ ] 8.12 Test de propiedad: resiliencia del IAEnricher ante errores de backend
    - **Property 20: Resiliencia del IAEnricher ante errores de backend**
    - **Valida: Requisitos 6.8**

  - [ ] 8.13 Test de propiedad: sugerencias publicitarias cumplen restricciones de formato
    - **Property 11: Las sugerencias publicitarias cumplen las restricciones de formato**
    - **Valida: Requisitos 17.2, 17.3**

- [ ] 9. Checkpoint — Verificar backend de IA y enriquecimiento
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

- [ ] 10. Captura, inferencia y detección de anomalías
  - [ ] 10.1 Implementar CaptureManager con multiprocessing
    - Crear `switch_bot/capture/capture_manager.py`
    - Implementar captura de 4 feeds de video (CSD/DSHOW) en proceso dedicado
    - Implementar captura de audio PCM continuo
    - Implementar `on_feed_disconnected()`: log + continuar con feeds restantes
    - Usar `multiprocessing.Queue` para enviar frames al proceso de inferencia
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 5.1, 5.2, 5.3_

  - [ ] 10.2 Test de propiedad: resiliencia ante desconexión parcial de feeds
    - **Property 13: Resiliencia ante desconexión parcial de feeds de video**
    - **Valida: Requisitos 1.3**

  - [ ] 10.3 Implementar InferenceEngine (MediaPipe + VAD)
    - Crear `switch_bot/inference/inference_engine.py`
    - Implementar `process_frame()`: MediaPipe gaze tracking sobre frame
    - Implementar `process_audio_chunk()`: VAD sobre chunk PCM
    - Garantizar ejecución dentro del frame time sin bloquear captura
    - Proceso dedicado con Queue de entrada y salida
    - _Requisitos: 2.1, 2.2, 2.3, 2.4_

  - [ ] 10.4 Implementar VocalAnomalyDetector
    - Crear `switch_bot/engines/vocal_anomaly_detector.py`
    - Implementar `analyze_segment()`: detectar TOS, ERROR_DICCION, CONFUSION, REPETICION
    - Integrar con IAEnricher para comparación contra patrones y guión (usa interfaz abstracta, agnóstico al backend)
    - Las anomalías generan marcadores sin cooldown (bypass de histéresis)
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 11. Checkpoint — Verificar captura, inferencia y anomalías
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

- [ ] 12. Gestión de sesión e inmutabilidad de backend
  - [ ] 12.1 Implementar SessionManager con control de ciclo de vida del backend
    - Crear `switch_bot/engines/session_manager.py`
    - Implementar inicio de sesión: validar backend accesible (timeout 10s), bloquear configuración
    - Implementar fin de sesión: desbloquear configuración, invocar generación de sugerencias publicitarias
    - Garantizar inmutabilidad del backend y modelos durante sesión activa
    - Implementar lógica de fallback: si backend no accesible → mensaje descriptivo + permitir seleccionar alternativo o reintentar sin reiniciar app
    - _Requisitos: 19.4, 19.5, 19.7_

  - [ ] 12.2 Test de propiedad: inmutabilidad de configuración de backend durante sesión activa
    - **Property 16: Inmutabilidad de configuración de backend durante sesión activa**
    - **Valida: Requisitos 19.7**

- [ ] 13. GUI, integración y cableado final
  - [ ] 13.1 Implementar GUI PyQt6 con controles de sesión y selector de backend IA
    - Crear `switch_bot/gui/main_window.py` con ventana principal PyQt6
    - Implementar selector de Backend IA: dropdown AWS Bedrock / Backend Local
    - Implementar selector de modelos: al elegir backend, poblar dropdowns con modelos disponibles (embedding + LLM) usando `list_available_models()`
    - Implementar indicador de estado de conexión del backend
    - Implementar botón "Validar conexión" y "Reintentar" con feedback visual
    - Implementar controles: selector de modo de video/fps, botones de inicio/parada de sesión
    - Implementar campo de texto para notas manuales y prompts de IA
    - Implementar botón de Panic Button prominente
    - Implementar indicadores de tally (QFrame) para las 4 cámaras
    - Implementar configuración de IP ATEM, URL OBS, directorio de salida
    - Deshabilitar selector de backend/modelos durante sesión activa (inmutabilidad visual)
    - _Requisitos: 4.1, 4.2, 4.3, 9.1, 10.3, 18.1, 18.2, 19.1, 19.2, 19.3, 19.5, 19.7, 19.9_

  - [ ] 13.2 Implementar Coordinator (orquestador principal)
    - Crear `switch_bot/coordinator.py`
    - Implementar event loop principal que conecta: CaptureManager → InferenceEngine → IAEnricher → DecisionEngine → HysteresisFilter → QuadDispatcher
    - Integrar PanicButton con prioridad inmediata
    - Integrar VocalAnomalyDetector en el flujo de audio
    - Integrar SessionManager para ciclo de vida de backend
    - Gestionar ciclo de vida de procesos (start/stop de sesión)
    - _Requisitos: 5.1, 5.2, 5.3, 16.1, 16.2, 16.3, 16.4_

  - [ ] 13.3 Implementar manejo de notas manuales y prompts de IA desde GUI
    - Conectar señales de la GUI al Coordinator vía `multiprocessing.Queue`
    - Notas manuales → Pipeline EDL con categoría MANUAL_NOTE, color Red
    - Prompts de IA → IAEnricher → marcador AI_PROMPT, color Magenta
    - Marcadores manuales/IA bypasean el filtro de histéresis
    - _Requisitos: 4.1, 4.2, 4.3, 4.4_

  - [ ] 13.4 Implementar presentación de sugerencias publicitarias al finalizar sesión
    - Al cerrar sesión, invocar `IAEnricher.generate_ad_suggestions()` y mostrar resultados en diálogo PyQt6
    - Presentar 3 sugerencias con texto propuesto y timecodes de referencia en formato legible
    - _Requisitos: 17.5_

  - [ ] 13.5 Escribir tests de integración del flujo completo
    - Test E2E: Captura mock → Inferencia → Decisión → 4 Pipelines
    - Test reconexión OBS: desconexión → reconexión → sincronización de escena
    - Test Pipeline ATEM: comando TCP a mock ATEM
    - Test selección de backend: cambio entre Bedrock y Local antes de sesión
    - Test validación de conexión: timeout de 10s + mensaje descriptivo
    - Test listado de modelos: Bedrock lista modelos AWS, Local lista modelos Ollama
    - _Requisitos: 16.2, 16.3, 11.3, 11.4, 10.1, 19.2, 19.3, 19.4, 19.5_

- [ ] 14. Checkpoint final — Verificar integración completa
  - Asegurar que todos los tests pasan, preguntar al usuario si surgen dudas.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Los tests de propiedades validan invariantes universales de corrección (usando Hypothesis)
- Los tests unitarios validan ejemplos específicos y edge cases
- El stack tecnológico es Python 3.11+ con multiprocessing, asyncio, threading, PyQt6, MediaPipe, PyAtemMax, boto3, httpx y obs-websocket-py
- El módulo `switch_bot/ia/` contiene toda la lógica de backend de IA con patrón Strategy
- La persistencia de configuración de backend usa `~/.switch_bot/config.json`
- El IAEnricher es agnóstico al backend: delega a BedrockBackend o LocalBackend según configuración del operador

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "1.5"] },
    { "id": 2, "tasks": ["1.3", "1.6", "1.7"] },
    { "id": 3, "tasks": ["1.8", "2.1", "2.5"] },
    { "id": 4, "tasks": ["2.2", "2.3", "2.4", "2.6"] },
    { "id": 5, "tasks": ["4.1", "4.3", "4.4", "4.7"] },
    { "id": 6, "tasks": ["4.2", "4.5", "4.6", "4.8"] },
    { "id": 7, "tasks": ["6.1"] },
    { "id": 8, "tasks": ["6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 9, "tasks": ["8.1", "8.3", "8.4"] },
    { "id": 10, "tasks": ["8.2", "8.5", "8.6", "8.7"] },
    { "id": 11, "tasks": ["8.8"] },
    { "id": 12, "tasks": ["8.9", "8.10", "8.11", "8.12", "8.13"] },
    { "id": 13, "tasks": ["10.1", "10.3"] },
    { "id": 14, "tasks": ["10.2", "10.4"] },
    { "id": 15, "tasks": ["12.1"] },
    { "id": 16, "tasks": ["12.2", "13.1"] },
    { "id": 17, "tasks": ["13.2"] },
    { "id": 18, "tasks": ["13.3", "13.4", "13.5"] }
  ]
}
```
