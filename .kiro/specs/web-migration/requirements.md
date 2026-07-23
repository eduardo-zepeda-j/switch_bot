# Requirements Document

## Introduction

Web-migration define la transformación del sistema Switch_bot desde una aplicación de escritorio monolítica (Python, PyQt6, multiprocessing) hacia una arquitectura híbrida cliente-servidor desplegada en AWS EC2. El sistema se divide en dos componentes: un servidor centralizado en EC2 que aloja la lógica de coordinación, el backend web (FastAPI + WebSocket), los pipelines de metadata/EDL, y el acceso a AWS Bedrock; y un agente local ligero en el PC del operador que ejecuta captura de video, inferencia MediaPipe, pipeline ATEM, modelos locales de IA y generación de timecodes SMPTE. La comunicación entre ambos es bidireccional en tiempo real mediante WebSocket/gRPC. El frontend web (SPA) reemplaza la GUI PyQt6 y es accesible desde cualquier navegador.

## Glossary

- **Servidor_EC2**: Instancia AWS EC2 que aloja el Coordinador, Motor_Decisión, Filtro_Histéresis, Enriquecedor_IA (modo Bedrock), Pipelines Metadata/EDL/OBS, SessionManager, Guión_Parser, backend web (FastAPI) y sirve el frontend SPA.
- **Agente_Local**: Proceso ligero que corre en el PC del operador, responsable de la captura de video, inferencia MediaPipe, pipeline ATEM, modelos locales de IA (Ollama/llama.cpp), VAD/audio PCM, indicadores de tally y generación de timecodes SMPTE.
- **Canal_Comunicación**: Enlace bidireccional en tiempo real (WebSocket y/o gRPC) entre el Agente_Local y el Servidor_EC2 para transmisión de resultados de inferencia, comandos de conmutación y sincronización de estado.
- **Frontend_SPA**: Aplicación web de página única (React, Vue o HTMX) servida desde el Servidor_EC2 que reemplaza la GUI PyQt6, accesible desde cualquier navegador.
- **SessionManager**: Componente del Servidor_EC2 que gestiona el ciclo de vida de sesiones de producción, autenticación de operadores y estado global.
- **Modo_Fallback**: Estado operativo autónomo del Agente_Local cuando la conexión con el Servidor_EC2 se interrumpe, manteniendo la captura, inferencia y conmutación ATEM sin funcionalidad centralizada.
- **Backend_Web**: Servidor FastAPI con endpoints REST y WebSocket que expone la API del sistema a los clientes Frontend_SPA y gestiona las conexiones de múltiples Agentes_Locales.
- **AI_Router**: Componente del Servidor_EC2 que determina si una solicitud de IA se procesa localmente (reenviándola al Agente_Local vía Canal_Comunicación) o en la nube (llamando directamente a AWS Bedrock).
- **Heartbeat**: Mensaje periódico enviado entre el Agente_Local y el Servidor_EC2 para detectar pérdida de conectividad.
- **State_Sync**: Protocolo de sincronización que reconcilia el estado del Agente_Local con el Servidor_EC2 tras una reconexión después de un período en Modo_Fallback.
- **UserStore**: Almacenamiento persistente (SQLite o equivalente) en el Servidor_EC2 que contiene los registros de usuarios del sistema, incluyendo credenciales hasheadas, roles y estado de activación.

## Requirements

### Requisito 1: Arquitectura Híbrida Servidor-Agente

**User Story:** Como arquitecto del sistema, quiero que Switch_bot se descomponga en un servidor centralizado (EC2) y un agente local ligero, para permitir acceso multi-operador desde cualquier navegador manteniendo las operaciones de baja latencia en hardware local.

#### Criterios de Aceptación

1. THE Servidor_EC2 SHALL alojar el Coordinador, Motor_Decisión, Filtro_Histéresis, Enriquecedor_IA (modo Bedrock), Pipelines Metadata/EDL/OBS, SessionManager y Guión_Parser como módulos desplegables en un único proceso FastAPI con aislamiento de responsabilidades por router.
2. THE Agente_Local SHALL ejecutar CaptureManager (4 feeds de video CSD/DSHOW), InferenceEngine (MediaPipe gaze tracking), Pipeline ATEM (TCP a switcher LAN), modelos locales de IA (Ollama/llama.cpp), VAD/Audio PCM y generación de timecodes SMPTE.
3. THE Servidor_EC2 SHALL servir el Frontend_SPA y el Backend_Web (FastAPI + WebSocket) en una única instancia EC2, exponiendo un endpoint WebSocket para la comunicación bidireccional con cada Agente_Local conectado.
4. THE Agente_Local SHALL operar como un proceso autónomo instalable en el PC del operador sin dependencia de PyQt6 ni componentes de GUI, comunicándose con el Servidor_EC2 exclusivamente mediante una conexión WebSocket persistente.
5. IF la conexión WebSocket entre el Agente_Local y el Servidor_EC2 se interrumpe, THEN THE Agente_Local SHALL continuar ejecutando las operaciones locales (captura, inferencia, Pipeline ATEM, modelos locales de IA) de forma autónoma y SHALL intentar reconexión automática cada 5 segundos hasta un máximo de 60 intentos antes de señalizar al operador un fallo de conectividad persistente.
6. THE Servidor_EC2 SHALL soportar conexiones simultáneas de hasta 4 operadores mediante sesiones WebSocket independientes gestionadas por el SessionManager, sin interferencia entre las sesiones activas.
7. WHILE un Agente_Local está reconectándose al Servidor_EC2, THE Agente_Local SHALL encolar los eventos generados localmente y transmitirlos al servidor en orden cronológico una vez restablecida la conexión.

### Requisito 2: Canal de Comunicación Bidireccional en Tiempo Real

**User Story:** Como operador de producción, quiero que el agente local y el servidor EC2 se comuniquen en tiempo real de forma bidireccional, para que los resultados de inferencia, comandos de conmutación y estado se sincronicen con latencia mínima.

#### Criterios de Aceptación

1. WHEN el Agente_Local genera un resultado de inferencia (gaze tracking, VAD), THE Canal_Comunicación SHALL transmitir dicho resultado al Servidor_EC2 en formato serializado con una latencia de extremo a extremo menor a 50 ms, medida en condiciones de red con latencia de ida (one-way) menor a 20 ms y sin pérdida de paquetes.
2. WHEN el Servidor_EC2 emite un comando de conmutación o payload enriquecido, THE Canal_Comunicación SHALL transmitir dicho mensaje al Agente_Local con una latencia de extremo a extremo menor a 50 ms, medida en condiciones de red con latencia de ida (one-way) menor a 20 ms y sin pérdida de paquetes.
3. THE Canal_Comunicación SHALL soportar WebSocket como protocolo primario de transporte con opción de gRPC como alternativa de alto rendimiento.
4. IF la conexión entre el Agente_Local y el Servidor_EC2 se interrumpe, THEN THE Canal_Comunicación SHALL iniciar reconexión automática con backoff exponencial comenzando en 1 segundo, duplicando el intervalo en cada intento hasta un máximo de 30 segundos, y realizando un máximo de 20 intentos antes de reportar fallo de conexión al operador.
5. WHILE la conexión está interrumpida y la reconexión está en curso, THE Canal_Comunicación SHALL almacenar en buffer local los mensajes salientes hasta un máximo de 500 mensajes o 10 MB (lo que se alcance primero), y transmitirlos en orden FIFO al restablecerse la conexión.
6. THE Canal_Comunicación SHALL aplicar compresión a los mensajes de datos de inferencia, reduciendo el tamaño de payload en al menos un 40% respecto al tamaño sin comprimir del mensaje serializado.
7. THE Canal_Comunicación SHALL autenticar cada conexión del Agente_Local mediante un token JWT o secreto compartido antes de aceptar datos.
8. IF el Agente_Local presenta un token de autenticación inválido o expirado, THEN THE Canal_Comunicación SHALL rechazar la conexión y registrar el intento fallido con la dirección de origen y el SMPTE_TC del evento.
9. THE Canal_Comunicación SHALL transmitir los mensajes preservando el orden de emisión dentro de cada dirección (Agente_Local→Servidor_EC2 y Servidor_EC2→Agente_Local), garantizando entrega ordenada tipo FIFO.

### Requisito 3: Localidad Obligatoria de Operaciones Críticas

**User Story:** Como arquitecto del sistema, quiero garantizar que las operaciones con requisitos de latencia sub-frame permanezcan en el Agente_Local, para preservar la calidad de producción en tiempo real.

#### Criterios de Aceptación

1. THE Agente_Local SHALL ejecutar la captura de video (CSD/DSHOW) exclusivamente en el hardware local sin transmitir frames raw ni datos de imagen sin procesar al Servidor_EC2.
2. THE Agente_Local SHALL ejecutar la inferencia MediaPipe (gaze tracking) localmente, transmitiendo al Servidor_EC2 solamente los vectores de resultados (coordenadas de mirada y landmarks faciales).
3. THE Agente_Local SHALL ejecutar el Pipeline ATEM (comandos TCP al switcher) exclusivamente en la red local (LAN) del operador, sin enrutar comandos de conmutación a través del Servidor_EC2.
4. THE Agente_Local SHALL generar timecodes SMPTE localmente y transmitirlos como datos numéricos al Servidor_EC2.
5. WHILE el sistema opera a la frecuencia configurada, THE Agente_Local SHALL completar el ciclo captura-inferencia-envío dentro del frame time correspondiente (16.67 ms a 60 fps, 33.33 ms a 30 fps, 33.37 ms a 29.97 fps) sin depender de respuesta del Servidor_EC2.
6. THE Agente_Local SHALL ejecutar el VAD (Voice Activity Detection) y la captura de audio PCM localmente, transmitiendo al Servidor_EC2 solamente los resultados de segmentación de habla (timestamps de inicio/fin de actividad vocal y identificador de hablante), sin transmitir muestras de audio raw.
7. IF el Agente_Local no completa el ciclo captura-inferencia-envío dentro del frame time configurado, THEN THE Agente_Local SHALL descartar el frame retrasado y continuar el procesamiento con el siguiente frame disponible, registrando el evento de frame drop en el log local.

### Requisito 4: Modo Fallback Autónomo del Agente Local

**User Story:** Como operador de producción, quiero que el agente local continúe operando de forma autónoma si la conexión con el servidor EC2 se pierde, para que la producción en vivo no se interrumpa por problemas de red.

#### Criterios de Aceptación

1. WHEN el Agente_Local detecta pérdida de conectividad con el Servidor_EC2 durante más de 3 Heartbeats consecutivos fallidos, THE Agente_Local SHALL activar el Modo_Fallback de forma automática.
2. WHILE el Agente_Local opera en Modo_Fallback, THE Agente_Local SHALL mantener la captura de video, inferencia MediaPipe, VAD y Pipeline ATEM funcionando con un Motor_Decisión local que toma decisiones de conmutación basándose exclusivamente en gaze tracking y VAD con el último mapeo personaje-cámara conocido, sin enriquecimiento semántico del Servidor_EC2 ni actualizaciones de contexto de guión.
3. WHILE el Agente_Local opera en Modo_Fallback, THE Agente_Local SHALL almacenar localmente todos los eventos, timecodes y resultados de inferencia en un buffer persistente en disco (que sobreviva reinicios del proceso) con una capacidad máxima de 24 horas de eventos acumulados, descartando los eventos más antiguos si se alcanza el límite.
4. WHEN la conectividad con el Servidor_EC2 se restablece, THE Agente_Local SHALL desactivar el Modo_Fallback, reanudar la operación normal delegando decisiones al Servidor_EC2, y ejecutar el protocolo State_Sync para transmitir los eventos acumulados durante el período de desconexión sin bloquear la operación en curso.
5. WHEN la conectividad con el Servidor_EC2 se restablece, THE Servidor_EC2 SHALL integrar los eventos del período de fallback en el log centralizado respetando el orden temporal de los timecodes SMPTE.
6. THE Agente_Local SHALL indicar visualmente al operador el estado de conectividad actual (conectado, reconectando, fallback) mediante los indicadores de tally locales, actualizando el indicador dentro de 1 segundo desde el cambio de estado.
7. IF el protocolo State_Sync falla durante la transmisión de eventos acumulados (por nueva desconexión o error de red), THEN THE Agente_Local SHALL conservar los eventos no transmitidos en el buffer persistente y reintentar la sincronización en la siguiente reconexión.

### Requisito 5: Enrutamiento de IA (Bedrock vs. Local)

**User Story:** Como operador de producción, quiero que el sistema enrute las solicitudes de IA al backend correcto según la configuración (Bedrock en EC2 o modelos locales en el agente), para escalar la IA en la nube o usar GPU local según mis necesidades.

#### Criterios de Aceptación

1. WHILE el Backend_IA activo es AWS Bedrock, THE AI_Router del Servidor_EC2 SHALL procesar las solicitudes de embeddings y análisis contextual invocando AWS Bedrock desde EC2 sin reenviar al Agente_Local.
2. WHILE el Backend_IA activo es un Backend_Local (Ollama/llama.cpp), THE AI_Router del Servidor_EC2 SHALL reenviar las solicitudes de IA al Agente_Local configurado para ese backend vía Canal_Comunicación para procesamiento en GPU local.
3. WHEN el AI_Router reenvía una solicitud al Agente_Local, THE Agente_Local SHALL procesar la solicitud con el runtime local (Ollama o llama.cpp) y retornar el resultado al Servidor_EC2 vía Canal_Comunicación.
4. THE AI_Router SHALL aplicar un timeout de 30 segundos para solicitudes reenviadas al Agente_Local y de 10 segundos para solicitudes a AWS Bedrock.
5. IF una solicitud de IA reenviada al Agente_Local excede el timeout de 30 segundos, THEN THE AI_Router SHALL registrar el fallo en el log indicando el SMPTE_TC del segmento afectado y marcar el segmento como no procesado sin detener la sesión.
6. IF una solicitud a AWS Bedrock excede el timeout de 10 segundos, THEN THE AI_Router SHALL registrar el fallo en el log indicando el SMPTE_TC del segmento afectado y marcar el segmento como no procesado sin detener la sesión.
7. IF el Agente_Local no está alcanzable al momento de reenviar una solicitud (conexión rechazada o sin respuesta), THEN THE AI_Router SHALL registrar el error en el log y marcar el segmento como no procesado sin detener la sesión.
8. THE AI_Router SHALL producir resultados con estructura de salida idéntica (embeddings vectoriales como lista de floats y análisis contextual con formato de marcadores EDL) independientemente del backend utilizado.

### Requisito 6: Frontend Web SPA

**User Story:** Como operador de producción, quiero acceder a la interfaz de Switch_bot desde cualquier navegador sin instalar software adicional, para controlar la producción desde cualquier dispositivo conectado a la red.

#### Criterios de Aceptación

1. THE Servidor_EC2 SHALL servir un Frontend_SPA accesible desde las últimas 2 versiones mayores de Chrome, Firefox, Safari y Edge sin instalación de plugins.
2. THE Frontend_SPA SHALL exponer todas las funcionalidades del operador: visualización de estado, inyección de notas manuales, prompts de IA, activación de Panic_Button, configuración de sesión y selección de Backend_IA.
3. THE Frontend_SPA SHALL recibir actualizaciones de estado en tiempo real (cámara activa, tally, timecode actual, estado de pipelines) vía WebSocket con latencia de actualización visual menor a 200 ms medidos desde la emisión del evento en el Servidor_EC2 hasta el renderizado en el navegador del operador.
4. THE Frontend_SPA SHALL soportar acceso concurrente de al menos 5 operadores a la misma sesión de producción, donde cada operador visualiza el mismo estado en tiempo real y las acciones de cada uno se procesan en orden de llegada al Backend_Web.
5. WHEN un operador inyecta una nota o activa el Panic_Button desde el Frontend_SPA, THE Backend_Web SHALL confirmar la recepción al cliente y propagar la acción al pipeline correspondiente dentro de 500 ms desde la solicitud del cliente.
6. IF un operador proporciona credenciales inválidas al intentar autenticarse en el Frontend_SPA, THEN THE Backend_Web SHALL rechazar el acceso y presentar un mensaje indicando fallo de autenticación sin revelar si el usuario existe, permitiendo un máximo de 5 intentos antes de bloquear el acceso durante 60 segundos.
7. THE Frontend_SPA SHALL requerir autenticación de operadores antes de permitir acceso a las funcionalidades de control de producción, y SHALL cerrar la sesión automáticamente tras 30 minutos de inactividad del operador.
8. IF la conexión WebSocket entre el Frontend_SPA y el Servidor_EC2 se interrumpe, THEN THE Frontend_SPA SHALL mostrar un indicador visual de desconexión al operador, deshabilitar los controles de acción, e intentar reconexión automática con reintentos cada 3 segundos hasta un máximo de 10 intentos antes de solicitar al operador reconexión manual.

### Requisito 7: Backend Web FastAPI

**User Story:** Como arquitecto del sistema, quiero que el backend web exponga una API REST y WebSocket bien definida, para que el Frontend_SPA y los Agentes_Locales se comuniquen con el servidor de forma estructurada y segura.

#### Criterios de Aceptación

1. THE Backend_Web SHALL exponer endpoints REST para operaciones CRUD de sesiones, configuración de backend de IA, carga de guiones y consulta de logs/EDL.
2. THE Backend_Web SHALL exponer endpoints WebSocket para comunicación en tiempo real con el Frontend_SPA (estado, tally, timecodes) y con los Agentes_Locales (inferencia, comandos), con latencia de propagación menor a 200 ms.
3. THE Backend_Web SHALL validar todos los payloads de entrada contra schemas definidos, retornando errores descriptivos con códigos HTTP estándar para solicitudes malformadas.
4. THE Backend_Web SHALL mantener separación de canales WebSocket: un canal dedicado para comunicación con Agentes_Locales y un canal dedicado para el Frontend_SPA.
5. THE Backend_Web SHALL soportar al menos 4 Agentes_Locales conectados simultáneamente, cada uno identificado por un ID de operador único.
6. IF un Agente_Local se desconecta del Backend_Web, THEN THE Backend_Web SHALL notificar al Frontend_SPA del cambio de estado del agente dentro de 2 segundos.
7. IF un mensaje WebSocket recibido de un Agente_Local o Frontend_SPA no cumple el schema esperado, THEN THE Backend_Web SHALL descartar el mensaje, registrar el error en el log y enviar un mensaje de error al emisor indicando el campo o tipo inválido.

### Requisito 8: Gestión Centralizada de Sesiones

**User Story:** Como director de producción, quiero que las sesiones de grabación se gestionen de forma centralizada en el servidor, para que múltiples operadores colaboren en la misma producción con estado compartido.

#### Criterios de Aceptación

1. THE SessionManager SHALL gestionar el ciclo de vida de sesiones con las siguientes transiciones válidas: creación → inicio, inicio → pausa, pausa → reanudación, inicio → finalización, pausa → finalización, reanudación → finalización.
2. THE SessionManager SHALL mantener el estado global de la sesión (cámara activa, timecode actual, historial de eventos, estado de pipelines) y propagarlo a todos los Agentes_Locales y Frontend_SPA conectados en un tiempo no superior a 500 ms desde la última modificación del estado.
3. WHEN un operador crea una nueva sesión, THE SessionManager SHALL asignar un identificador único (UUID v4) y registrar la configuración inicial (modo de video, Backend_IA, guión cargado).
4. THE SessionManager SHALL permitir que entre 2 y 8 Agentes_Locales participen en una sesión simultáneamente, cada uno controlando su propio hardware local (ATEM, cámaras).
5. WHEN una sesión finaliza, THE SessionManager SHALL consolidar los logs, EDL y metadata generados durante la sesión escribiéndolos en almacenamiento persistente del Servidor_EC2, y SHALL confirmar la consolidación completa antes de marcar la sesión como finalizada.
6. THE SessionManager SHALL persistir el estado de sesión en almacenamiento del Servidor_EC2 con un intervalo máximo de 5 segundos entre escrituras, de forma que un reinicio del Servidor_EC2 permita recuperar sesiones activas con una pérdida máxima de 5 segundos de datos acumulados.
7. IF un Agente_Local se desconecta durante una sesión activa, THEN THE SessionManager SHALL registrar el evento de desconexión con el SMPTE_TC del momento, preservar el estado de la sesión para los demás participantes, y permitir la reconexión del Agente_Local sin reiniciar la sesión.
8. IF dos o más operadores emiten comandos conflictivos sobre el mismo recurso de sesión simultáneamente, THEN THE SessionManager SHALL aplicar orden de llegada (first-write-wins) y notificar al operador cuyo comando fue rechazado indicando el conflicto.
9. IF la consolidación de logs, EDL o metadata falla durante la finalización de sesión, THEN THE SessionManager SHALL reintentar la operación hasta 3 veces con un intervalo de 2 segundos entre intentos, y SHALL notificar al operador si la consolidación no se completa tras los reintentos.

### Requisito 9: Logs y Metadata Centralizados

**User Story:** Como director de postproducción, quiero que todos los logs, archivos EDL y metadata se almacenen de forma centralizada en el servidor EC2, para tener un único punto de acceso a los artefactos de producción.

#### Criterios de Aceptación

1. THE Servidor_EC2 SHALL almacenar todos los archivos de log (.jsonl), EDL (.edl) y DRP (.drp) generados durante las sesiones de producción en almacenamiento persistente que sobreviva reinicios del servidor.
2. THE Backend_Web SHALL exponer endpoints REST para listado paginado (máximo 100 resultados por página) y descarga de logs y artefactos de sesión, permitiendo filtrar por operador, rango de fecha y identificador de sesión.
3. WHEN el Agente_Local transmite eventos al Servidor_EC2, THE Pipeline_Metadata SHALL registrar cada evento con el SMPTE_TC original generado localmente y un timestamp de recepción del servidor en formato ISO 8601.
4. THE Servidor_EC2 SHALL mantener la integridad temporal de los eventos ordenándolos por SMPTE_TC local independientemente del orden de recepción en el servidor.
5. WHEN la sesión de grabación es finalizada por el operador, THE Servidor_EC2 SHALL exponer los archivos EDL y DRP consolidados para descarga dentro de los 60 segundos posteriores a la finalización.
6. IF el Agente_Local pierde conectividad con el Servidor_EC2 durante una sesión activa, THEN THE Agente_Local SHALL almacenar los eventos localmente y retransmitirlos al Servidor_EC2 cuando la conexión se restablezca, preservando el SMPTE_TC original de cada evento.
7. IF la retransmisión de eventos pendientes falla después de 3 intentos consecutivos, THEN THE Agente_Local SHALL registrar el fallo en el log local e informar al operador que existen eventos no sincronizados con el servidor.

### Requisito 10: Heartbeat y Detección de Conectividad

**User Story:** Como operador de producción, quiero que el sistema detecte rápidamente la pérdida de conexión entre el agente local y el servidor, para activar el modo fallback antes de que la producción se vea afectada.

#### Criterios de Aceptación

1. THE Agente_Local SHALL enviar un mensaje Heartbeat al Servidor_EC2 cada 1 segundo.
2. WHEN el Servidor_EC2 recibe un Heartbeat del Agente_Local, THE Servidor_EC2 SHALL enviar un mensaje Heartbeat de respuesta al Agente_Local dentro de 500 ms.
3. WHEN el Agente_Local no recibe respuesta de Heartbeat durante 3 ciclos consecutivos (3 segundos), THE Agente_Local SHALL marcar la conexión como perdida y activar el Modo_Fallback de forma automática.
4. WHEN el Servidor_EC2 no recibe un Heartbeat de un Agente_Local durante 5 segundos, THE Servidor_EC2 SHALL marcar al agente como desconectado y enviar una notificación de cambio de estado al Frontend_SPA indicando el identificador del agente y el timestamp de la última comunicación exitosa.
5. THE Heartbeat SHALL incluir un timestamp del emisor en formato ISO 8601 con precisión de milisegundos y un número de secuencia entero de 64 bits monótonamente creciente para detectar paquetes fuera de orden.
6. IF el Agente_Local recibe un Heartbeat de respuesta con un número de secuencia menor o igual al último procesado, THEN THE Agente_Local SHALL descartar el mensaje y no reiniciar el contador de ciclos fallidos.
7. WHEN el Agente_Local en Modo_Fallback recibe una respuesta de Heartbeat válida del Servidor_EC2, THE Agente_Local SHALL considerar la conexión como restablecida e iniciar el protocolo State_Sync.

### Requisito 11: Sincronización de Estado Post-Reconexión

**User Story:** Como operador de producción, quiero que al recuperarse la conexión con el servidor, todos los eventos generados durante el modo fallback se sincronicen correctamente, para no perder información de producción.

#### Criterios de Aceptación

1. WHEN la conectividad con el Servidor_EC2 se restablece tras un período de Modo_Fallback, THE Agente_Local SHALL iniciar el protocolo State_Sync dentro de los 5 segundos siguientes, enviando los eventos acumulados al Servidor_EC2 en orden cronológico ascendente de SMPTE_TC.
2. THE State_Sync SHALL transmitir los eventos acumulados en lotes de máximo 50 eventos por lote, requiriendo confirmación de recepción (ACK) por cada lote dentro de un timeout de 10 segundos antes de enviar el siguiente lote.
3. WHEN el Servidor_EC2 recibe eventos del State_Sync, THE Servidor_EC2 SHALL integrar los eventos en el log centralizado intercalándolos con los eventos existentes según su SMPTE_TC.
4. IF durante el State_Sync se detectan conflictos de estado (decisiones de conmutación contradictorias entre el agente y el servidor para el mismo SMPTE_TC durante el período de desconexión), THEN THE Servidor_EC2 SHALL preservar ambas versiones marcando los conflictos con un flag CONFLICT para resolución manual.
5. THE State_Sync SHALL ejecutar la transmisión de eventos en un proceso o thread independiente sin bloquear la operación de captura, inferencia ni ejecución de pipelines del Agente_Local ni del Servidor_EC2.
6. IF el State_Sync no recibe ACK de un lote dentro del timeout de 10 segundos, THEN THE Agente_Local SHALL reintentar el envío del mismo lote hasta un máximo de 3 intentos, y si persiste el fallo, SHALL pausar la sincronización, preservar los eventos pendientes en almacenamiento local y notificar al operador indicando el número de eventos no sincronizados.
7. WHEN el State_Sync completa la transmisión exitosa de todos los eventos acumulados, THE Agente_Local SHALL notificar al operador indicando la cantidad de eventos sincronizados y el rango de SMPTE_TC cubierto.
8. THE Agente_Local SHALL acumular un máximo de 10,000 eventos durante el Modo_Fallback; IF se alcanza este límite, THEN THE Agente_Local SHALL continuar operando y sobrescribir los eventos más antiguos, registrando un aviso en el log local.

### Requisito 12: Serialización del Canal de Comunicación

**User Story:** Como desarrollador del sistema, quiero que los mensajes entre el agente local y el servidor se serialicen con un formato definido y validable, para garantizar la integridad de la comunicación bidireccional.

#### Criterios de Aceptación

1. THE Canal_Comunicación SHALL serializar todos los mensajes en formato JSON con un schema versionado que incluya: tipo de mensaje (string), timestamp en formato ISO 8601 con precisión de milisegundos, número de secuencia (entero unsigned de 64 bits) y payload con un tamaño máximo de 1 MB.
2. THE Canal_Comunicación SHALL deserializar mensajes recibidos validando la presencia y tipo de datos de todos los campos obligatorios del schema (tipo de mensaje, timestamp, número de secuencia, versión de protocolo y payload) antes de procesar el payload.
3. THE Canal_Comunicación SHALL garantizar que serializar y luego deserializar cualquier mensaje válido produzca un objeto con igualdad profunda de todos los campos respecto al original (propiedad round-trip).
4. THE Canal_Comunicación SHALL incluir un campo de versión de protocolo en formato "MAJOR.MINOR" en cada mensaje, donde mensajes con el mismo MAJOR son compatibles en lectura independientemente del MINOR.
5. IF un mensaje recibido no cumple el schema esperado (campos faltantes, tipos incorrectos, payload excede 1 MB o versión MAJOR no soportada), THEN THE Canal_Comunicación SHALL descartar el mensaje, registrar el error en el log con el motivo de rechazo y solicitar retransmisión al emisor.
6. IF el emisor no responde a la solicitud de retransmisión dentro de 5 segundos o se han realizado 3 intentos de retransmisión fallidos para el mismo número de secuencia, THEN THE Canal_Comunicación SHALL registrar la pérdida del mensaje en el log y continuar procesando mensajes subsiguientes.

### Requisito 13: Seguridad y Autenticación

**User Story:** Como administrador del sistema, quiero que todas las comunicaciones estén autenticadas y cifradas, para prevenir acceso no autorizado al sistema de producción.

#### Criterios de Aceptación

1. THE Backend_Web SHALL requerir autenticación mediante JWT (JSON Web Token) con expiración de 24 horas para todos los endpoints REST y conexiones WebSocket del Frontend_SPA.
2. IF un cliente presenta un JWT ausente, inválido o expirado, THEN THE Backend_Web SHALL rechazar la solicitud con código HTTP 401 Unauthorized sin revelar el motivo específico del rechazo al cliente.
3. THE Canal_Comunicación SHALL requerir autenticación del Agente_Local mediante un token pre-compartido o certificado TLS mutuo antes de aceptar datos.
4. IF el Agente_Local presenta credenciales inválidas (token incorrecto o certificado no reconocido), THEN THE Canal_Comunicación SHALL rechazar la conexión, registrar el intento fallido con IP de origen y timestamp en el log de seguridad, y no enviar datos al agente.
5. THE Backend_Web SHALL cifrar todas las comunicaciones mediante TLS 1.2 o superior tanto para conexiones REST como WebSocket.
6. THE SessionManager SHALL implementar control de acceso basado en roles con los siguientes permisos: operador (inyectar notas, Panic_Button, visualizar estado), director (crear/finalizar sesiones, configurar Backend_IA, descargar artefactos), administrador (gestionar usuarios, modificar roles, acceso a logs de seguridad).
7. IF un intento de autenticación falla 5 veces consecutivas desde la misma dirección IP, THEN THE Backend_Web SHALL bloquear la dirección IP durante 15 minutos y registrar el evento en el log de seguridad.

### Requisito 14: Preservación de Compatibilidad con Tests Existentes

**User Story:** Como desarrollador del sistema, quiero que la migración preserva la compatibilidad con la suite de tests existente (605 tests), para garantizar que la lógica de negocio migrada funciona correctamente.

#### Criterios de Aceptación

1. THE Servidor_EC2 SHALL mantener las interfaces públicas (firmas de métodos, tipos de parámetros, tipos de retorno y excepciones declaradas) del Coordinador, Motor_Decisión, Filtro_Histéresis, Enriquecedor_IA, Motor_EDL y Compilador_DRP sin modificaciones respecto a la versión monolítica, de modo que los tests unitarios y de propiedad existentes se ejecuten sin cambios en imports ni invocaciones.
2. THE Agente_Local SHALL mantener las interfaces públicas (firmas de métodos, tipos de parámetros, tipos de retorno y excepciones declaradas) del CaptureManager e InferenceEngine sin modificaciones respecto a la versión monolítica, de modo que los tests existentes se ejecuten sin cambios en imports ni invocaciones.
3. WHEN un componente se migra del monolito al Servidor_EC2 o al Agente_Local, THE componente migrado SHALL pasar el 100% de los tests existentes asociados (605 tests en total) sin modificaciones en las aserciones ni en la lógica de los tests.
4. THE Pipeline_Metadata SHALL producir archivos .jsonl con estructura de campos, orden de claves y formato de valores idénticos byte a byte a los producidos por el sistema monolítico, validable mediante comparación directa de salidas ante las mismas entradas de test.
5. THE Motor_EDL SHALL producir archivos EDL CMX 3600 con contenido idéntico byte a byte al producido por el sistema monolítico, validable mediante comparación directa de salidas ante las mismas entradas de test.
6. IF un componente migrado introduce un fallo de comunicación entre Servidor_EC2 y Agente_Local durante la ejecución de tests, THEN THE componente migrado SHALL propagar el error de forma equivalente a una excepción local, sin alterar el comportamiento observable por los tests existentes.
7. WHEN se completa la migración de un componente, THE suite de tests SHALL ejecutarse en su totalidad y reportar 0 tests fallidos y 0 errores nuevos respecto a la ejecución previa a la migración.

### Requisito 15: Escalabilidad Multi-Operador

**User Story:** Como director de producción, quiero que múltiples operadores accedan y controlen la producción simultáneamente desde diferentes ubicaciones, para permitir colaboración remota en producciones complejas.

#### Criterios de Aceptación

1. THE Servidor_EC2 SHALL soportar al menos 4 Agentes_Locales conectados simultáneamente a una misma sesión de producción.
2. THE Frontend_SPA SHALL soportar al menos 10 clientes web conectados simultáneamente visualizando el estado de la misma sesión, incluyendo la escena activa, el log de marcadores y el estado del Panic_Button.
3. WHEN múltiples operadores envían comandos simultáneos, THE SessionManager SHALL serializar las acciones de control (Panic_Button, notas, prompts) aplicando orden FIFO con timestamp del servidor, procesando cada comando en el orden de llegada sin descartar ninguno.
4. THE Backend_Web SHALL propagar cambios de estado (conmutaciones de escena, marcadores añadidos, activación/desactivación de Panic_Button y cambios de estado de sesión) a todos los clientes conectados (Frontend_SPA y Agentes_Locales) dentro de 200 ms desde que el cambio ocurre en el servidor.
5. WHILE múltiples Agentes_Locales operan en la misma sesión, THE Servidor_EC2 SHALL recibir los resultados de inferencia de todos los agentes y alimentar el Motor_Decisión con el resultado del agente asignado como fuente primaria según la configuración de la sesión.
6. IF un Agente_Local pierde conexión con el Servidor_EC2 durante una sesión activa, THEN THE Servidor_EC2 SHALL registrar la desconexión en el log con el SMPTE_TC del evento, excluir al agente desconectado del flujo de decisión, y continuar la sesión con los agentes restantes sin interrumpir la producción.
7. WHEN un cliente (Frontend_SPA o Agente_Local) se conecta a una sesión en curso, THE Backend_Web SHALL enviar el estado completo actual de la sesión (escena activa, estado de Panic_Button, último timecode y lista de agentes conectados) al nuevo cliente dentro de 500 ms desde la conexión.

### Requisito 16: Gestión de Usuarios y Login

**User Story:** Como administrador del sistema, quiero gestionar usuarios con credenciales seguras y controlar el acceso al Frontend_SPA mediante un sistema de login, para que solo personal autorizado pueda operar el sistema de producción.

#### Criterios de Aceptación

1. WHEN el Servidor_EC2 se ejecuta por primera vez y no existe ningún usuario en el almacenamiento persistente, THE Servidor_EC2 SHALL crear un usuario root con las credenciales configuradas mediante variables de entorno (SWITCHBOT_ROOT_USERNAME y SWITCHBOT_ROOT_PASSWORD), asignándole el rol "administrador" y estado activo.
2. THE Servidor_EC2 SHALL almacenar las contraseñas de todos los usuarios exclusivamente en formato hash utilizando bcrypt o argon2 con un costo computacional mínimo de 12 rounds (bcrypt) o 3 iteraciones (argon2), sin almacenar contraseñas en texto plano en ningún momento.
3. WHEN un usuario con rol "administrador" solicita crear un nuevo usuario, THE Backend_Web SHALL crear el usuario con los campos: username (único, entre 3 y 64 caracteres alfanuméricos), contraseña hasheada, rol asignado (operador, director o administrador), estado activo (true por defecto), fecha de creación (ISO 8601) y último login (null hasta primer acceso).
4. WHEN un usuario con rol "administrador" solicita listar, consultar o actualizar usuarios, THE Backend_Web SHALL permitir la operación y retornar los datos del usuario sin incluir el hash de la contraseña en la respuesta.
5. WHEN un usuario con rol "administrador" solicita eliminar un usuario, THE Backend_Web SHALL verificar que el usuario objetivo no es el usuario root; IF el usuario objetivo es el usuario root, THEN THE Backend_Web SHALL rechazar la operación con un error descriptivo indicando que el usuario root no puede ser eliminado.
6. WHEN un usuario con rol "administrador" solicita desactivar un usuario, THE Backend_Web SHALL marcar el usuario como inactivo (active=false) sin eliminar su registro del almacenamiento, preservando el historial de auditoría y los logs asociados al usuario desactivado.
7. WHEN un cliente envía credenciales (username y password) al endpoint de login, THE Backend_Web SHALL validar las credenciales contra el hash almacenado; IF las credenciales son válidas y el usuario está activo, THEN THE Backend_Web SHALL generar un JWT con claims de user_id y role, actualizar el campo last_login del usuario, y retornar el token al cliente.
8. IF un cliente envía credenciales inválidas (username inexistente, contraseña incorrecta o usuario inactivo) al endpoint de login, THEN THE Backend_Web SHALL rechazar la autenticación con un mensaje genérico de credenciales inválidas sin revelar cuál campo es incorrecto, y SHALL registrar el intento fallido con la dirección IP de origen.
9. WHEN un usuario autenticado solicita cambiar su propia contraseña, THE Backend_Web SHALL verificar la contraseña actual del usuario antes de aceptar la nueva contraseña, y SHALL almacenar la nueva contraseña hasheada reemplazando el hash anterior.
10. WHEN un usuario con rol "administrador" solicita restablecer la contraseña de otro usuario, THE Backend_Web SHALL permitir la operación sin requerir la contraseña anterior del usuario objetivo, almacenando la nueva contraseña hasheada.
11. IF un usuario no autenticado o con rol distinto de "administrador" intenta realizar operaciones CRUD sobre usuarios, THEN THE Backend_Web SHALL rechazar la solicitud con código HTTP 403 Forbidden.
12. THE Backend_Web SHALL almacenar los registros de usuario en un almacenamiento persistente (SQLite o equivalente) que sobreviva reinicios del Servidor_EC2, con un índice único sobre el campo username para garantizar unicidad.
