# Requirements Document

## Introduction

Switch_bot es un sistema de automatización de producción multicámara en tiempo real. Captura feeds de video desde múltiples fuentes, procesa audio con detección de actividad vocal, compara el contenido en vivo contra un guión pre-cargado mediante IA (AWS Bedrock o modelos locales como Ollama/llama.cpp), y ejecuta decisiones de conmutación de cámara de forma autónoma. El operador puede seleccionar el backend de IA y los modelos específicos a utilizar según su entorno. Genera archivos EDL (CMX 3600) y DRP (DaVinci Resolve Project) en tiempo real, enriquecidos con marcadores contextuales clasificados por origen y color.

## Glossary

- **Switch_bot**: Sistema principal de automatización de producción multicámara en tiempo real.
- **Motor_EDL**: Subsistema responsable de generar y escribir archivos EDL en formato CMX 3600 con marcadores de color.
- **Compilador_DRP**: Subsistema que genera archivos de proyecto DaVinci Resolve en formato JSON Lines (.drp).
- **Motor_Decisión**: Componente que evalúa los datos de inferencia y contexto para determinar cortes de cámara.
- **Filtro_Histéresis**: Componente que aplica un cooldown mínimo entre conmutaciones de cámara para prevenir cambios erráticos.
- **Enriquecedor_IA**: Componente de enriquecimiento semántico que abstrae el backend de IA utilizado. Soporta múltiples backends: AWS Bedrock (Titan Embeddings V2, Claude 3.5) y modelos locales (Ollama, llama.cpp, GGUF).
- **Backend_IA**: Proveedor concreto de modelos de IA. Puede ser AWS Bedrock (cloud) o un runtime local (Ollama, llama.cpp).
- **Modelo_IA**: Modelo específico de lenguaje o embeddings disponible dentro de un Backend_IA (por ejemplo: Claude 3.5 Sonnet en Bedrock, o Llama 3 en Ollama).
- **Backend_Local**: Instancia de Backend_IA que ejecuta modelos en la máquina del operador sin conexión a la nube, utilizando runtimes como Ollama o llama.cpp con modelos en formato GGUF u otros formatos locales.
- **Pipeline_ATEM**: Canal de ejecución que envía comandos TCP asíncronos al switcher ATEM físico vía PyAtemMax.
- **Pipeline_OBS**: Canal de ejecución que controla OBS Studio mediante protocolo MCP (WebSockets/SSE).
- **Pipeline_Metadata**: Canal de ejecución que mantiene el log append-only (.jsonl) y sintetiza el archivo .drp.
- **Clasificador_Notas**: Componente dentro del Motor_EDL que categoriza marcadores según su fuente (Manual, IA/Contexto).
- **SMPTE_TC**: Timecode en formato SMPTE (HH:MM:SS:FF) alineado a Time of Day (TOD).
- **VAD**: Voice Activity Detection — detección de actividad vocal en el stream de audio.
- **Detector_Anomalías_Vocales**: Componente que identifica pausas por tos, errores de dicción, confusiones y repeticiones en el audio en vivo para generar marcadores automáticos.
- **Guión_Parser**: Componente que carga y estructura documentos de guión (PDF/Markdown/JSON) en memoria para comparación en tiempo real.
- **Payload_Enriquecido**: Estructura JSON unificada que contiene personaje, cámara destino, tipo de marcador, nota y timecode de entrada.
- **Panic_Button**: Mecanismo de override manual que pausa la automatización o inyecta banderas de emergencia.

## Requirements

### Requisito 1: Captura Multicanal Asíncrona

**User Story:** Como operador de producción, quiero que el sistema capture simultáneamente 4 feeds de video y un stream de audio PCM, para que toda la información de las cámaras esté disponible para la toma de decisiones en tiempo real.

#### Criterios de Aceptación

1. THE Switch_bot SHALL capturar simultáneamente 4 feeds de video mediante interfaces CSD/DSHOW a la frecuencia configurada del sistema.
2. THE Switch_bot SHALL capturar el stream de audio PCM desde los micrófonos de forma continua durante toda la sesión de grabación.
3. WHEN un feed de video se desconecta, THE Switch_bot SHALL registrar el evento en el log y continuar operando con los feeds restantes.
4. THE Switch_bot SHALL soportar las frecuencias de cuadro de 60 fps, 30 fps y 29.97 fps como opciones configurables del sistema.

### Requisito 2: Detección de Actividad Vocal e Inferencia MediaPipe

**User Story:** Como operador de producción, quiero que el sistema detecte quién está hablando y hacia dónde mira cada participante, para que las decisiones de corte se basen en el contexto real de la conversación.

#### Criterios de Aceptación

1. THE Switch_bot SHALL ejecutar inferencia MediaPipe sobre los feeds de video para tracking de mirada (gaze tracking).
2. THE Switch_bot SHALL ejecutar Voice Activity Detection (VAD) sobre el stream de audio PCM para identificar segmentos de habla activa.
3. WHILE el sistema opera a 30 fps, THE Switch_bot SHALL completar la inferencia de cada frame dentro del frame time configurado (33.33 ms) sin bloquear la captura de video.
4. THE Switch_bot SHALL asociar la actividad vocal detectada con el personaje correspondiente según el mapeo definido en el guión cargado.

### Requisito 3: Ingesta y Parsing de Guión Previo

**User Story:** Como director de producción, quiero cargar un guión estructurado antes de la sesión, para que el sistema compare el contenido en vivo contra el guión planificado.

#### Criterios de Aceptación

1. THE Guión_Parser SHALL aceptar documentos de guión en formato PDF, Markdown y JSON.
2. THE Guión_Parser SHALL extraer la estructura de bloques, cues, mapeo de personajes y escenas del documento cargado.
3. WHEN un documento de guión válido se carga, THE Guión_Parser SHALL generar una representación en memoria indexada por bloques y personajes.
4. IF el documento de guión tiene un formato no reconocido, THEN THE Guión_Parser SHALL reportar un error descriptivo indicando el formato esperado.

### Requisito 4: Control en Vivo mediante App/GUI

**User Story:** Como operador de producción, quiero inyectar notas manuales, activar marcadores rápidos y enviar prompts de IA durante la producción, para enriquecer el EDL con información contextual en tiempo real.

#### Criterios de Aceptación

1. WHEN el operador presiona un botón de nota rápida en la App, THE Switch_bot SHALL registrar la nota con el SMPTE_TC activo al momento de la pulsación.
2. WHEN el operador ingresa texto libre mediante teclado o UI, THE Switch_bot SHALL inyectar dicho texto como marcador manual en el pipeline EDL.
3. WHEN el operador envía un prompt de IA, THE Enriquecedor_IA SHALL procesar el prompt y generar un marcador contextual enriquecido.
4. THE Switch_bot SHALL procesar marcadores manuales y de IA de forma instantánea sin aplicar el cooldown del Filtro_Histéresis.

### Requisito 5: Memoria Compartida y Aislamiento de Procesos

**User Story:** Como arquitecto del sistema, quiero que los procesos de captura, inferencia y ejecución estén completamente aislados, para que ningún bloqueo en un proceso afecte el frame time de la captura.

#### Criterios de Aceptación

1. THE Switch_bot SHALL utilizar multiprocessing.Queue con un Thread Event Loop como mecanismo de comunicación entre procesos.
2. THE Switch_bot SHALL enrutar los datos de video al proceso de inferencia y los prompts/notas al pipeline EDL de forma independiente.
3. THE Switch_bot SHALL mantener aislamiento total entre procesos para prevenir que un bloqueo en inferencia o generación de archivos afecte la captura de video.

### Requisito 6: Enriquecimiento Semántico con IA Multi-Backend

**User Story:** Como director de producción, quiero que el sistema compare automáticamente el audio en vivo con el guión cargado y genere marcadores inteligentes utilizando el backend de IA configurado (AWS Bedrock o modelos locales), para identificar desviaciones del guión sin intervención manual y sin depender exclusivamente de servicios en la nube.

#### Criterios de Aceptación

1. WHEN el guión ha sido cargado y parseado por el Guión_Parser, THE Enriquecedor_IA SHALL vectorizar el guión completo utilizando el modelo de embeddings del Backend_IA activo como base RAG antes de que la sesión de grabación inicie la comparación en vivo.
2. WHEN el VAD detecta un segmento de habla finalizado, THE Enriquecedor_IA SHALL utilizar el modelo de lenguaje del Backend_IA activo para comparar la transcripción de dicho segmento contra el guión vectorizado y determinar un score de similitud semántica entre 0.0 y 1.0.
3. WHEN el score de similitud semántica de un segmento es inferior a 0.7 respecto al bloque de guión esperado, THE Enriquecedor_IA SHALL generar un comentario EDL con categoría SCRIPT_DEVIATION, color asignado, y metadatos que incluyan: el texto del segmento detectado, el texto esperado del guión, y el score de similitud obtenido.
4. WHEN el operador envía un prompt manual al Enriquecedor_IA, THE Enriquecedor_IA SHALL procesar el prompt y generar un marcador con categoría AI_PROMPT y color Magenta en un tiempo no superior a 10 segundos.
5. THE Enriquecedor_IA SHALL formatear los comentarios generados según el estándar CMX 3600 con la sintaxis: `|C:{Color} |M:{TIPO_MARCADOR} |D:1`.
6. WHILE el Backend_IA activo es AWS Bedrock, THE Enriquecedor_IA SHALL utilizar Titan Embeddings V2 para embeddings y Claude 3.5 Sonnet o Haiku para análisis contextual.
7. WHILE el Backend_IA activo es un Backend_Local, THE Enriquecedor_IA SHALL utilizar los modelos de embeddings y lenguaje seleccionados por el operador en la configuración del backend local.
8. IF el Backend_IA activo no responde o retorna un error durante la comparación de un segmento, THEN THE Enriquecedor_IA SHALL registrar el fallo en el log con el SMPTE_TC del segmento afectado y continuar procesando los segmentos subsiguientes sin detener la sesión.

### Requisito 7: Detección de Anomalías Vocales y Marcadores de Error

**User Story:** Como director de producción, quiero que el sistema detecte automáticamente pausas por tos, errores de dicción, confusiones y repeticiones, para marcar esos momentos en el EDL y facilitar la corrección en postproducción.

#### Criterios de Aceptación

1. WHEN el Detector_Anomalías_Vocales identifica una pausa prolongada causada por tos en el audio, THE Motor_EDL SHALL registrar un marcador con categoría TOS y color Red en el SMPTE_TC del evento.
2. WHEN el Detector_Anomalías_Vocales identifica un error de dicción (palabra mal pronunciada o trabada), THE Motor_EDL SHALL registrar un marcador con categoría ERROR_DICCION y color Red en el SMPTE_TC del evento.
3. WHEN el Detector_Anomalías_Vocales identifica una confusión del hablante (cambio involuntario de tema, frase incoherente), THE Motor_EDL SHALL registrar un marcador con categoría CONFUSION y color Red en el SMPTE_TC del evento.
4. WHEN el Detector_Anomalías_Vocales identifica una repetición (el hablante repite una frase o bloque), THE Motor_EDL SHALL registrar un marcador con categoría REPETICION y color Red en el SMPTE_TC del evento.
5. THE Detector_Anomalías_Vocales SHALL utilizar el Enriquecedor_IA para comparar la transcripción del audio en vivo contra patrones de error conocidos y el contexto del guión cargado, independientemente del Backend_IA activo.
6. THE Detector_Anomalías_Vocales SHALL procesar las anomalías detectadas sin aplicar el cooldown del Filtro_Histéresis, permitiendo marcadores consecutivos si ocurren múltiples errores en secuencia.

### Requisito 8: Motor de Decisión y Filtro de Histéresis

**User Story:** Como operador de producción, quiero que el sistema aplique un cooldown entre cortes de cámara automáticos, para evitar cambios erráticos que degraden la calidad visual de la producción.

#### Criterios de Aceptación

1. THE Motor_Decisión SHALL evaluar los datos de inferencia (gaze tracking, VAD, contexto de guión) para determinar la cámara destino óptima.
2. THE Filtro_Histéresis SHALL imponer un cooldown mínimo de 90 frames (3 segundos a 30 fps) entre conmutaciones automáticas de cámara.
3. WHEN un marcador manual o de IA se recibe, THE Filtro_Histéresis SHALL permitir su procesamiento inmediato sin aplicar cooldown.
4. WHILE el cooldown del Filtro_Histéresis está activo, THE Motor_Decisión SHALL mantener la escena actual y rechazar nuevas solicitudes automáticas de conmutación.

### Requisito 9: Panic Button y Override Manual

**User Story:** Como operador de producción, quiero poder pausar la automatización o inyectar banderas de emergencia en cualquier momento, para mantener control humano sobre la producción.

#### Criterios de Aceptación

1. WHEN el operador activa el Panic_Button, THE Switch_bot SHALL pausar todas las conmutaciones automáticas de cámara de forma inmediata.
2. WHEN el operador activa el Panic_Button, THE Motor_EDL SHALL registrar una bandera de emergencia en el archivo EDL con el SMPTE_TC del momento de activación.
3. WHEN el operador desactiva el Panic_Button, THE Switch_bot SHALL reanudar la operación automática desde el estado actual.
4. THE Panic_Button SHALL responder en un tiempo menor a un frame time (33.33 ms a 30 fps) desde la activación física.

### Requisito 10: Pipeline ATEM — Conmutación de Hardware

**User Story:** Como operador de producción, quiero que el sistema controle el switcher ATEM físico de forma autónoma, para que las cámaras SDI/HDMI se conmuten según las decisiones del Motor de Decisión.

#### Criterios de Aceptación

1. THE Pipeline_ATEM SHALL enviar comandos TCP asíncronos al switcher ATEM mediante la librería PyAtemMax.
2. THE Pipeline_ATEM SHALL operar en un worker thread dedicado para los sockets de control ATEM ISO sin bloquear la interfaz de usuario.
3. THE Pipeline_ATEM SHALL actualizar el indicador visual de tally (QFrame) cada 33.33 ms para reflejar la cámara activa.
4. WHEN el Motor_Decisión selecciona una cámara destino, THE Pipeline_ATEM SHALL conmutar la entrada del mix effect block al source index correspondiente.

### Requisito 11: Pipeline OBS — Conmutación de Software

**User Story:** Como operador de producción, quiero que el sistema controle OBS Studio en paralelo al ATEM, para tener una salida de software sincronizada con la conmutación de hardware.

#### Criterios de Aceptación

1. THE Pipeline_OBS SHALL enviar eventos JSON/MCP a OBS Studio mediante WebSockets o SSE.
2. WHEN el Motor_Decisión selecciona una cámara destino, THE Pipeline_OBS SHALL cambiar a la escena OBS correspondiente al personaje y encuadre seleccionado.
3. IF la conexión WebSocket con OBS Studio se interrumpe, THEN THE Pipeline_OBS SHALL intentar reconexión asíncrona de forma automática sin afectar los demás pipelines.
4. WHEN la reconexión con OBS Studio se restablece, THE Pipeline_OBS SHALL sincronizar el estado actual de la escena con el Motor_Decisión.

### Requisito 12: Pipeline Metadata y Logging

**User Story:** Como director de postproducción, quiero que el sistema mantenga un log estructurado de todas las acciones y genere un archivo .drp para DaVinci Resolve, para facilitar la edición posterior.

#### Criterios de Aceptación

1. THE Pipeline_Metadata SHALL escribir cada evento en un archivo append-only .jsonl con ID de personaje, timecode SMPTE y nota asociada, delegando la I/O de disco (write + flush + fsync) a un thread del pool via asyncio.to_thread para no bloquear el event loop ni la ejecución de los demás pipelines.
2. THE Compilador_DRP SHALL generar la primera línea del archivo .drp con la configuración completa del proyecto: versión, masterTimecode, videoMode, array de sources (Black, Camera 1-4, Color Bars, Color 1-2, Media Player 1), mixEffectBlocks, downstreamKeys y recordingId.
3. WHEN el Motor_Decisión ejecuta un corte de cámara, THE Compilador_DRP SHALL agregar una nueva línea JSON al archivo .drp con el masterTimecode y el source index actualizado.
4. THE Compilador_DRP SHALL generar archivos .drp compatibles con el formato JSON Lines (newline-delimited JSON) de DaVinci Resolve.
5. THE Compilador_DRP SHALL formatear timecodes con separador punto y coma (;) para indicar Drop Frame en modo 29.97 fps.

### Requisito 13: Pipeline Multi-Marker EDL Engine

**User Story:** Como editor de video, quiero recibir un archivo EDL CMX 3600 con marcadores clasificados por color y origen, para localizar rápidamente los puntos de interés durante la postproducción.

#### Criterios de Aceptación

1. THE Motor_EDL SHALL generar archivos EDL válidos según el estándar CMX 3600, incluyendo cabecera TITLE y FCM: NON-DROP FRAME.
2. THE Clasificador_Notas SHALL categorizar cada marcador según su fuente: Manual (operador) o IA/Contexto (Bedrock/Guión).
3. THE Motor_EDL SHALL asignar códigos de color a los marcadores según la siguiente clasificación: Red para MANUAL_NOTE, TOS, ERROR_DICCION, CONFUSION y REPETICION; Green para SCRIPT_MATCH; Magenta para AI_PROMPT; Cyan para ENTRADA; Yellow para SALIDA.
4. THE Motor_EDL SHALL formatear cada evento como un evento de 1 frame con la sintaxis: `NNN  001      V     C        TC_IN TC_OUT TC_IN TC_OUT` seguido de un comentario `|C:ResolveColor{Color} |M:{TIPO} |D:1`.
5. THE Motor_EDL SHALL escribir el archivo .edl de forma atómica (flush + fsync) y non-blocking (delegando la I/O de disco a un thread del pool via asyncio.to_thread) en tiempo real durante la sesión de producción, sin bloquear la ejecución de los demás pipelines.
6. THE Motor_EDL SHALL numerar los eventos EDL de forma secuencial comenzando en 001 con formato de 3 dígitos.

### Requisito 14: Serialización y Round-Trip del Formato DRP

**User Story:** Como desarrollador del sistema, quiero que el parser/generador de archivos .drp garantice fidelidad bidireccional, para que los archivos generados se importen correctamente en DaVinci Resolve y puedan re-leerse por el sistema.

#### Criterios de Aceptación

1. THE Compilador_DRP SHALL serializar objetos de configuración de proyecto a formato JSON Lines válido.
2. THE Compilador_DRP SHALL parsear archivos .drp existentes reconstruyendo la configuración de proyecto y la secuencia de eventos de conmutación.
3. FOR ALL configuraciones de proyecto válidas, parsear y luego serializar un archivo .drp SHALL producir un archivo equivalente al original (propiedad round-trip).
4. THE Compilador_DRP SHALL preservar el orden y la precisión de los timecodes en todas las operaciones de lectura y escritura.

### Requisito 15: Serialización y Round-Trip del Formato EDL

**User Story:** Como desarrollador del sistema, quiero que el parser/generador de archivos EDL CMX 3600 garantice fidelidad bidireccional, para que los marcadores se preserven correctamente entre escritura y lectura.

#### Criterios de Aceptación

1. THE Motor_EDL SHALL serializar eventos de marcador a formato texto CMX 3600 válido.
2. THE Motor_EDL SHALL parsear archivos EDL existentes reconstruyendo la lista de eventos con sus timecodes, colores y tipos de marcador.
3. FOR ALL listas de eventos válidas, parsear y luego serializar un archivo EDL SHALL producir un archivo equivalente al original (propiedad round-trip).
4. THE Motor_EDL SHALL preservar la alineación de columnas y el formato de timecode SMPTE (HH:MM:SS:FF) en todas las operaciones de serialización.

### Requisito 16: Ejecución Sincrónica Cuádruple

**User Story:** Como arquitecto del sistema, quiero que los 4 pipelines se ejecuten en paralelo con un payload unificado, para garantizar que la conmutación de hardware, software, metadata y EDL ocurran de forma coordinada.

#### Criterios de Aceptación

1. WHEN el Motor_Decisión aprueba un evento, THE Switch_bot SHALL construir un Payload_Enriquecido con: personaje, cámara destino (target_cam), tipo de marcador (marker_type), nota descriptiva y timecode de entrada (tc_in).
2. THE Switch_bot SHALL despachar el Payload_Enriquecido simultáneamente a los 4 pipelines (ATEM, OBS, Metadata, EDL).
3. WHILE los 4 pipelines procesan un evento, THE Switch_bot SHALL garantizar que la falla de un pipeline individual no bloquee la ejecución de los demás.
4. THE Switch_bot SHALL completar el despacho del Payload_Enriquecido a todos los pipelines dentro de un frame time (33.33 ms a 30 fps).

### Requisito 17: Generación de Sugerencias Publicitarias Post-Sesión

**User Story:** Como productor de contenido, quiero recibir 3 sugerencias de texto para spots publicitarios de 15-30 segundos al finalizar la grabación, para agilizar la creación de material promocional basado en el contenido real de la sesión.

#### Criterios de Aceptación

1. WHEN la sesión de grabación finaliza, THE Enriquecedor_IA SHALL analizar el log completo de la sesión (.jsonl) junto con el guión cargado para identificar los momentos de mayor relevancia.
2. THE Enriquecedor_IA SHALL generar exactamente 3 sugerencias de texto publicitario, cada una diseñada para un spot de 15 a 30 segundos de duración.
3. THE Enriquecedor_IA SHALL incluir en cada sugerencia: un timecode de inicio (tc_in) y un timecode de fin (tc_out) que referencien el segmento de video relevante.
4. THE Enriquecedor_IA SHALL basar las sugerencias en los segmentos con mayor densidad de coincidencias con el guión (SCRIPT_MATCH) y menor cantidad de anomalías vocales.
5. THE Switch_bot SHALL presentar las 3 sugerencias al operador en formato legible al concluir la sesión, incluyendo el texto propuesto y los timecodes de referencia.

### Requisito 18: Configuración del Sistema y Modos de Video

**User Story:** Como operador de producción, quiero configurar el modo de video y la frecuencia de cuadro del sistema antes de iniciar la sesión, para adaptar el sistema a los requisitos técnicos de cada producción.

#### Criterios de Aceptación

1. THE Switch_bot SHALL soportar el modo de video 1080p29.97 como modo de operación predeterminado.
2. THE Switch_bot SHALL permitir configurar la frecuencia del sistema entre 60 fps, 30 fps y 29.97 fps antes del inicio de sesión.
3. WHEN la frecuencia del sistema se configura a 30 fps, THE Switch_bot SHALL establecer el frame time en 33.33 ms y el cooldown de histéresis en 90 frames.
4. THE Switch_bot SHALL alinear todos los timecodes SMPTE al modo TOD (Time of Day) durante la sesión activa.

### Requisito 19: Configuración y Selección de Backend de IA

**User Story:** Como operador de producción, quiero seleccionar el backend de IA (AWS Bedrock o modelos locales) y elegir qué modelos usar dentro de ese backend, para operar el sistema con o sin conexión a la nube según los recursos disponibles en mi entorno.

#### Criterios de Aceptación

1. THE Switch_bot SHALL permitir al operador seleccionar el Backend_IA activo entre AWS Bedrock y Backend_Local antes del inicio de sesión.
2. WHEN el operador selecciona AWS Bedrock como Backend_IA, THE Switch_bot SHALL listar los modelos disponibles en la cuenta configurada y permitir al operador elegir el modelo de embeddings y el modelo de lenguaje.
3. WHEN el operador selecciona Backend_Local como Backend_IA, THE Switch_bot SHALL consultar los modelos disponibles en el runtime local (Ollama, llama.cpp) y permitir al operador elegir el modelo de embeddings y el modelo de lenguaje.
4. WHEN el operador inicia la sesión de grabación, THE Switch_bot SHALL validar que el Backend_IA seleccionado esté accesible dentro de un timeout máximo de 10 segundos.
5. IF el Backend_IA seleccionado no está accesible al iniciar sesión, THEN THE Switch_bot SHALL informar al operador con un mensaje descriptivo indicando el backend y el motivo del fallo, y SHALL permitir al operador seleccionar un backend alternativo o reintentar la conexión sin reiniciar la aplicación.
6. THE Switch_bot SHALL almacenar la configuración del Backend_IA seleccionado y los modelos elegidos de forma persistente entre reinicios de la aplicación para reutilizarla en sesiones futuras.
7. WHILE una sesión está activa, THE Switch_bot SHALL mantener el Backend_IA y los modelos seleccionados sin permitir cambios hasta que la sesión finalice.
8. THE Enriquecedor_IA SHALL operar independientemente del Backend_IA activo, produciendo resultados con la misma estructura de salida (embeddings vectoriales para RAG y análisis contextual por LLM con formato de marcadores idéntico) con ambos backends.
9. IF la consulta de modelos disponibles falla al seleccionar un Backend_IA (por error de red, credenciales inválidas o runtime local no iniciado), THEN THE Switch_bot SHALL informar al operador con un mensaje indicando la causa del fallo y SHALL permitir reintentar la consulta o seleccionar el otro backend.
