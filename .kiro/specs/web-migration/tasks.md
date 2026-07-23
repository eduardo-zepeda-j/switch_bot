# Implementation Plan: Web Migration

## Overview

Migración de Switch_bot desde una aplicación monolítica PyQt6 a una arquitectura híbrida cliente-servidor (Servidor_EC2 + Agente_Local) con comunicación WebSocket bidireccional, Frontend SPA (HTMX + Alpine.js), y despliegue en AWS EC2. La implementación sigue un orden de dependencias: protocolo de canal → infraestructura WebSocket → heartbeat/fallback → sincronización → IA routing → sesiones → auth → backend FastAPI → frontend → integración/tests.

## Tasks

- [x] 1. Protocolo de canal y serialización (ChannelMessage + msgspec)
  - [x] 1.1 Implementar ChannelMessage y payload structs con msgspec
    - Crear módulo `switch_bot/web/protocol.py`
    - Definir `ChannelMessage(msgspec.Struct)` con campos: type, timestamp, seq, version, payload
    - Implementar métodos `validate()`, `encode()`, `decode()`
    - Definir MESSAGE_TYPES como Literal con todos los tipos de mensaje del protocolo
    - Implementar payload structs: HeartbeatPayload, InferenceResultPayload, SwitchCommandPayload, StateUpdatePayload, AIRequestPayload, AIResponsePayload, StateSyncBatchPayload, StateSyncAckPayload
    - Validar tamaño máximo de payload (1 MB), campos obligatorios y versión de protocolo "MAJOR.MINOR"
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 1.2 Escribir unit tests para serialización/deserialización
    - Test round-trip: encode → decode produce igualdad profunda para cada tipo de payload
    - Test validación: mensajes con campos faltantes, tipos incorrectos o payload > 1MB son rechazados
    - Test compatibilidad de versión: mismo MAJOR con diferente MINOR son compatibles
    - Test rechazo de MAJOR no soportado
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 2. Infraestructura WebSocket del servidor (WebSocketHub)
  - [x] 2.1 Implementar WebSocketHub con canales separados agente/SPA
    - Crear módulo `switch_bot/web/hub.py`
    - Implementar `WebSocketHub` con diccionarios separados para conexiones de agentes y SPAs
    - Implementar `register_agent()` y `register_spa_client()` con validación de token
    - Implementar `unregister_agent()` con notificación a SPAs conectados
    - Implementar `broadcast_to_spas()`, `send_to_agent()`, `broadcast_to_agents()`
    - Limitar max_agents=4 y max_spa_clients=10
    - _Requirements: 1.3, 1.6, 7.4, 7.5, 15.1, 15.2_

  - [x] 2.2 Escribir unit tests para WebSocketHub
    - Test registro/desregistro de agentes y SPAs
    - Test broadcast a SPAs cuando un agente se desconecta
    - Test rechazo de conexiones que exceden límites
    - Test separación de canales (mensajes de agente no llegan a SPA y viceversa)
    - _Requirements: 7.4, 7.5, 7.6_

- [x] 3. Checkpoint - Verificar protocolo y hub
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. HeartbeatManager y detección de conectividad
  - [x] 4.1 Implementar HeartbeatManager del servidor
    - Crear módulo `switch_bot/web/heartbeat.py`
    - Implementar `HeartbeatManager` con monitoreo periódico cada 1s
    - Implementar `process_heartbeat()` que valida seq number y genera ACK con timestamp
    - Detectar agente desconectado si no recibe heartbeat en 5 segundos
    - Invocar callback `on_disconnect` cuando se detecta pérdida de conectividad
    - Descartar heartbeats con seq <= último procesado (out-of-order)
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 10.6_

  - [x] 4.2 Implementar AgentWebSocketClient con heartbeat y reconnection
    - Crear módulo `switch_bot/web/agent_client.py`
    - Implementar `AgentWebSocketClient` con conexión autenticada via JWT
    - Implementar heartbeat cada 1s con detección de desconexión tras 3 ciclos fallidos
    - Implementar `reconnect_with_backoff()`: exponencial 1s → 30s max, 20 intentos
    - Implementar `send_message()` que encola en buffer local si desconectado
    - Invocar `on_heartbeat_timeout()` que activa FallbackManager
    - _Requirements: 1.4, 1.5, 2.4, 10.1, 10.3, 10.5, 10.7_

  - [x] 4.3 Escribir unit tests para heartbeat y reconexión
    - Test detección de 3 heartbeats fallidos activa fallback
    - Test ACK con seq inválido es descartado
    - Test backoff exponencial respeta 1s→2s→4s→8s→16s→30s max
    - Test reconexión exitosa tras recuperar heartbeat válido
    - _Requirements: 10.1, 10.2, 10.3, 10.6, 10.7_

- [x] 5. FallbackManager y buffer persistente
  - [x] 5.1 Implementar FallbackManager con SQLite WAL
    - Crear módulo `switch_bot/web/fallback.py`
    - Implementar `FallbackManager` con SQLite WAL para durabilidad
    - Crear tabla `fallback_events` con campos: id, smpte_tc, event_type, payload, created_at, synced, sync_attempts
    - Implementar `activate()` que inicia Motor_Decisión local
    - Implementar `deactivate()` que inicia StateSyncProtocol
    - Implementar `store_event()` con descarte FIFO de eventos más antiguos si se alcanza MAX_EVENTS=10000
    - Implementar `get_pending_events(batch_size=50)` para obtener lotes ordenados por SMPTE_TC
    - Implementar `mark_synced()` para marcar eventos transmitidos
    - Verificar capacidad máxima de 24 horas de eventos
    - _Requirements: 4.1, 4.2, 4.3, 4.7, 11.8_

  - [x] 5.2 Escribir unit tests para FallbackManager
    - Test activación/desactivación de modo fallback
    - Test persistencia de eventos sobrevive reinicio del proceso
    - Test descarte FIFO al alcanzar MAX_EVENTS
    - Test get_pending_events retorna en orden cronológico SMPTE_TC
    - _Requirements: 4.1, 4.3, 4.7_

- [x] 6. StateSyncProtocol
  - [x] 6.1 Implementar StateSyncProtocol no bloqueante
    - Crear módulo `switch_bot/web/state_sync.py`
    - Implementar `StateSyncProtocol` con BATCH_SIZE=50, ACK_TIMEOUT=10s, MAX_RETRIES=3
    - Implementar `start_sync()` que ejecuta en asyncio.Task independiente (no bloqueante)
    - Implementar `send_batch()` que envía lote y espera ACK con timeout 10s
    - Implementar `handle_ack()` que marca eventos como sincronizados
    - Implementar `handle_conflict()` que preserva ambas versiones con flag CONFLICT
    - Reintentar lote fallido hasta 3 veces; si persiste, pausar sync y notificar operador
    - Al completar, notificar operador con cantidad de eventos y rango SMPTE_TC
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x] 6.2 Escribir unit tests para StateSyncProtocol
    - Test envío de lotes de 50 eventos con ACK exitoso
    - Test timeout de ACK provoca reintento (max 3)
    - Test conflictos se marcan con flag CONFLICT
    - Test sync no bloquea operaciones en tiempo real
    - _Requirements: 11.2, 11.4, 11.5, 11.6_

- [x] 7. Checkpoint - Verificar heartbeat, fallback y sync
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. AIRouter (enrutamiento Bedrock vs Local)
  - [x] 8.1 Implementar AIRouter con timeout diferenciado
    - Crear módulo `switch_bot/web/ai_router.py`
    - Implementar `AIRouter` con BEDROCK_TIMEOUT=10s y LOCAL_TIMEOUT=30s
    - Implementar `route_request()` que enruta según `active_backend` ("bedrock" o "local")
    - Implementar `_process_bedrock()` que invoca AWS Bedrock via boto3 con timeout 10s
    - Implementar `_forward_to_agent()` que reenvía al agente vía WebSocketHub con timeout 30s
    - Registrar fallos de timeout con SMPTE_TC del segmento afectado
    - Garantizar estructura de salida idéntica independientemente del backend
    - Marcar segmentos no procesados sin detener la sesión
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 8.2 Escribir unit tests para AIRouter
    - Test enrutamiento a Bedrock cuando backend=bedrock
    - Test forward a agente cuando backend=local
    - Test timeout 10s en Bedrock marca segmento como no procesado
    - Test timeout 30s en local marca segmento como no procesado
    - Test estructura de salida idéntica para ambos backends
    - _Requirements: 5.4, 5.5, 5.6, 5.7, 5.8_

- [ ] 9. SessionManagerWeb (gestión centralizada multi-operador)
  - [ ] 9.1 Implementar SessionManagerWeb extendiendo SessionManager
    - Crear módulo `switch_bot/web/session_manager.py`
    - Implementar `SessionManagerWeb(SessionManager)` con herencia del SessionManager existente
    - Implementar `create_session()` con UUID v4 y validación de rol director
    - Implementar `join_session()` con límite de MAX_AGENTS=8
    - Implementar `propagate_state()` que envía estado a agentes + SPAs en <500ms
    - Implementar `handle_conflict()` con resolución first-write-wins
    - Implementar `finalize_session()` con consolidación de logs/EDL/metadata y retry 3x
    - Implementar `recover_sessions()` para recuperación post-reinicio (máx 5s pérdida)
    - Implementar persistencia periódica cada 5s en SQLite
    - Implementar transiciones de estado válidas: created→started, started→paused, paused→started, started/paused→finalized
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

  - [ ] 9.2 Escribir unit tests para SessionManagerWeb
    - Test transiciones válidas e inválidas de estado de sesión
    - Test first-write-wins para comandos conflictivos
    - Test propagación de estado a todos los conectados
    - Test consolidación con retry en caso de fallo
    - Test límite de 8 agentes por sesión
    - _Requirements: 8.1, 8.4, 8.5, 8.8, 8.9_

- [ ] 10. AuthService (JWT + RBAC + rate limiting)
  - [ ] 10.1 Implementar AuthService con JWT, RBAC y bloqueo por IP
    - Crear módulo `switch_bot/web/auth.py`
    - Implementar `AuthService` con PyJWT (expiración 24h)
    - Implementar `create_token()` con claims de user_id y role
    - Implementar `validate_token()` que retorna claims o None
    - Implementar `check_permission()` basado en roles: operador, director, administrador
    - Implementar `record_failed_attempt()` con bloqueo tras 5 intentos (60s SPA, 15min IP)
    - Implementar `is_ip_blocked()` para verificar bloqueo activo
    - No revelar motivo específico de rechazo al cliente (401 genérico)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.6, 13.7, 6.6, 6.7_

  - [ ] 10.2 Escribir unit tests para AuthService
    - Test generación y validación de JWT válido
    - Test rechazo de token expirado o inválido
    - Test permisos RBAC para cada rol
    - Test bloqueo de IP tras 5 intentos fallidos
    - Test desbloqueo tras período de lockout
    - _Requirements: 13.1, 13.2, 13.6, 13.7_

- [ ] 11. Checkpoint - Verificar AI Router, sesiones y auth
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 21. UserStore — Persistencia de usuarios y login (Requisito 16)
  - [ ] 21.1 Agregar dependencia passlib[bcrypt] al proyecto
    - Añadir `passlib[bcrypt]` a la sección de dependencias en `pyproject.toml`
    - Verificar instalación con import de `passlib.hash.bcrypt`
    - _Requirements: 16.2_

  - [ ] 21.2 Implementar UserStore con SQLite, hashing y CRUD
    - Crear módulo `switch_bot/web/user_store.py`
    - Implementar clase `UserStore` con constructor `__init__(db_path, auth_service, hash_backend="bcrypt")`
    - Implementar `initialize()`: crear tabla users con schema definido en diseño (id, username, hashed_password, role, active, created_at, last_login), índice único en username
    - Implementar `_create_root_user()`: leer SWITCHBOT_ROOT_USERNAME y SWITCHBOT_ROOT_PASSWORD del entorno, crear usuario root con rol "administrador" y active=True. Raise RuntimeError si variables ausentes
    - Implementar `hash_password(plain)` y `verify_password(plain, hashed)` usando passlib bcrypt (12 rounds) con verificación timing-safe
    - Implementar CRUD: `create_user(username, plain_password, role)` con validación regex `[a-zA-Z0-9_-]{3,64}`, `get_user(username)`, `list_users()`, `update_user(username, fields)`, `delete_user(username)` (rechaza root con PermissionError), `deactivate_user(username)`
    - Implementar `change_password(username, current, new)` que verifica contraseña actual antes de aceptar nueva
    - Implementar `reset_password(username, new)` sin verificar contraseña anterior (para admins)
    - Implementar `authenticate(username, password)` que valida credenciales, verifica active=True, actualiza last_login y genera JWT via AuthService
    - Crear dataclass `User` con campos: id, username, hashed_password, role, active, created_at, last_login
    - _Requirements: 16.1, 16.2, 16.3, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.12_

  - [ ] 21.3 Implementar endpoints REST de autenticación y usuarios
    - Crear módulo `switch_bot/web/routers/auth_router.py` con prefix `/api/auth`
    - Implementar `POST /api/auth/login`: validar credenciales via UserStore.authenticate(), integrar rate-limiting de AuthService (5 intentos → 60s lockout SPA, 15min IP block), retornar LoginResponse con JWT
    - Implementar `PUT /api/auth/password`: cambiar contraseña del usuario autenticado (requiere current_password)
    - Crear módulo `switch_bot/web/routers/users_router.py` con prefix `/api/users`
    - Implementar `GET /api/users/` (solo admin): listar usuarios sin hashed_password
    - Implementar `POST /api/users/` (solo admin): crear usuario con validación de username y rol
    - Implementar `GET /api/users/{username}` (solo admin): obtener usuario específico
    - Implementar `PUT /api/users/{username}` (solo admin): actualizar role/active
    - Implementar `DELETE /api/users/{username}` (solo admin): eliminar usuario (403 si root)
    - Implementar `PUT /api/users/{username}/password` (solo admin): reset password sin contraseña anterior
    - Implementar dependencias `get_current_user()` y `require_admin()` con decoradores FastAPI
    - Usar schemas msgspec: LoginRequest, LoginResponse, CreateUserRequest, UpdateUserRequest, ChangePasswordRequest, ResetPasswordRequest, UserResponse
    - Retornar mensajes genéricos en errores de autenticación (no revelar campo incorrecto)
    - _Requirements: 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11_

  - [ ]* 21.4 Escribir unit tests para UserStore
    - Test `test_user_store_init_creates_root`: creación de root en primera ejecución con env vars
    - Test `test_user_store_init_no_env_vars_fails`: fallo si SWITCHBOT_ROOT_USERNAME/PASSWORD no definidos
    - Test `test_hash_round_trip`: hash_password + verify_password retorna True para misma contraseña
    - Test `test_create_user_valid_username`: creación exitosa con username válido
    - Test `test_create_user_invalid_username_rejected`: rechazo de usernames fuera de patrón
    - Test `test_delete_root_raises_permission_error`: eliminación de root rechazada
    - Test `test_deactivate_preserves_record`: usuario inactivo sigue existiendo en store
    - Test `test_login_returns_jwt_with_correct_claims`: estructura del JWT (user_id, role, exp)
    - Test `test_login_updates_last_login`: last_login se actualiza tras login exitoso
    - Test `test_login_generic_error_for_all_failure_modes`: mismo mensaje para user inexistente, password incorrecta, y user inactivo
    - Test `test_deactivated_user_cannot_login`: active=False impide autenticación
    - Test `test_change_password_requires_correct_current`: falla si current_password es incorrecta
    - _Requirements: 16.1, 16.2, 16.3, 16.5, 16.6, 16.7, 16.8, 16.9_

  - [ ]* 21.5 Escribir property test — Property 1: Password hash round-trip
    - **Property 1: Password hash round-trip**
    - Para cualquier contraseña válida (text, min_size=1, max_size=128), hash_password() seguido de verify_password(plain, hashed) retorna True, y el hash nunca contiene el plaintext como substring
    - Usar generador `hypothesis.strategies.text(min_size=1, max_size=128)`
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.2**

  - [ ]* 21.6 Escribir property test — Property 2: Username validation accepts only conforming inputs
    - **Property 2: Username validation accepts only conforming inputs**
    - Para cualquier string, create_user() lo acepta como username sii cumple `[a-zA-Z0-9_-]{3,64}`. Strings fuera del patrón son rechazados con ValueError y el store no cambia
    - Usar generadores `text()` para strings arbitrarios + `from_regex(r'[a-zA-Z0-9_-]{3,64}')` para válidos
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.3**

  - [ ]* 21.7 Escribir property test — Property 3: Password hash never exposed in user retrieval
    - **Property 3: Password hash never exposed in user retrieval**
    - Para cualquier usuario creado, get_user() y list_users() al serializar a UserResponse nunca incluyen hashed_password
    - Usar usuarios generados con campos aleatorios
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.4**

  - [ ]* 21.8 Escribir property test — Property 4: Root user is undeletable
    - **Property 4: Root user is undeletable**
    - Para cualquier secuencia de delete_user() apuntando al root username, el root permanece en el store con rol "administrador" y active sin cambios
    - Usar secuencias aleatorias de operaciones delete
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.5**

  - [ ]* 21.9 Escribir property test — Property 5: Deactivation preserves user record
    - **Property 5: Deactivation preserves user record**
    - Para cualquier usuario activo, deactivate_user() establece active=False y el usuario sigue recuperable con todos los demás campos (id, username, role, created_at) sin cambios
    - Usar usuarios aleatorios con campos variados
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.6**

  - [ ]* 21.10 Escribir property test — Property 6: Login authentication round-trip
    - **Property 6: Login authentication round-trip**
    - Para cualquier usuario con active=True y password conocida, authenticate(username, correct_password) retorna JWT non-None, y authenticate(username, wrong_password) retorna None. Para active=False, siempre retorna None
    - Usar passwords aleatorios + mutaciones para "wrong"
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.7, 16.8**

  - [ ]* 21.11 Escribir property test — Property 7: Password change round-trip
    - **Property 7: Password change round-trip**
    - Tras change_password(username, current, new) o reset_password(username, new) exitoso, verify_password(new, stored_hash) retorna True y verify_password(old, stored_hash) retorna False. change_password() con current incorrecto falla sin modificar hash
    - Usar pares (old_password, new_password) aleatorios
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.9, 16.10**

  - [ ]* 21.12 Escribir property test — Property 8: RBAC enforcement on user CRUD
    - **Property 8: RBAC enforcement on user CRUD**
    - Para cualquier usuario con rol "operador" o "director", todas las operaciones de gestión de usuarios (create, list, get, update, delete) son rechazadas con HTTP 403 y el store no cambia
    - Usar roles no-admin + operaciones CRUD aleatorias
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.11**

  - [ ]* 21.13 Escribir property test — Property 9: Username uniqueness constraint
    - **Property 9: Username uniqueness constraint**
    - Para cualquier username existente en el store, crear un segundo usuario con el mismo username falla con error y el store contiene exactamente un usuario con ese username
    - Usar usernames válidos duplicados
    - Mínimo 100 iteraciones
    - **Validates: Requirements 16.12**

  - [ ]* 21.14 Escribir integration tests para flujo completo de usuarios
    - Test `test_full_login_flow_e2e`: Init → create user → login → usar JWT en endpoint protegido → change password → re-login
    - Test `test_admin_user_lifecycle`: Create → get → update role → deactivate → verify cannot login → admin reset password → reactivate → verify can login
    - Test `test_rate_limiting_blocks_after_5_failures`: 5 intentos fallidos → siguiente retorna 429/403
    - Test `test_concurrent_user_creation_same_username`: solo una creación tiene éxito bajo concurrencia
    - Usar httpx AsyncClient con TestClient de FastAPI
    - _Requirements: 16.1, 16.3, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11, 16.12_

- [ ] 22. Checkpoint - Verificar UserStore y gestión de usuarios
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Backend FastAPI (REST + WebSocket endpoints)
  - [ ] 12.1 Crear estructura de aplicación FastAPI con routers
    - Crear módulo `switch_bot/web/app.py` con la aplicación FastAPI principal
    - Configurar routers: auth_router, session_router, config_router, logs_router, scripts_router
    - Implementar middleware de autenticación JWT para todos los endpoints
    - Configurar Uvicorn con uvloop para el event loop
    - Montar archivos estáticos para el SPA
    - _Requirements: 7.1, 7.3, 1.3_

  - [ ] 12.2 Implementar endpoints WebSocket para agentes y SPA
    - Implementar endpoint `/ws/agent/{operator_id}` con autenticación JWT
    - Implementar endpoint `/ws/spa/{client_id}` con autenticación JWT
    - Integrar WebSocketHub para gestión de conexiones
    - Validar schemas de mensajes recibidos y descartar inválidos con log de error
    - Enviar mensaje de error al emisor indicando campo/tipo inválido
    - Notificar al SPA dentro de 2s cuando un agente se desconecta
    - _Requirements: 7.2, 7.4, 7.5, 7.6, 7.7, 2.7, 2.8_

  - [ ] 12.3 Implementar endpoints REST (sesiones, config, logs, scripts)
    - Implementar CRUD de sesiones: crear, listar, obtener estado, pausar, finalizar
    - Implementar configuración de Backend_IA (Bedrock/Local)
    - Implementar carga de guiones (scripts)
    - Implementar listado paginado de logs (max 100/página) con filtros por operador, fecha, sesión
    - Implementar descarga de artefactos EDL/DRP
    - Validar payloads contra schemas con errores HTTP descriptivos
    - _Requirements: 7.1, 7.3, 9.1, 9.2, 9.5_

  - [ ] 12.4 Escribir integration tests para endpoints REST y WebSocket
    - Test conexión WebSocket con token válido e inválido
    - Test CRUD completo de sesiones via REST
    - Test validación de schemas y error responses
    - Test listado paginado de logs con filtros
    - Test propagación de estado via WebSocket al SPA
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7_

- [ ] 13. Configuración TLS y Nginx reverse proxy
  - [ ] 13.1 Crear configuración Nginx para TLS termination y WebSocket proxy
    - Crear archivo de configuración Nginx con TLS 1.2+ (certificados Let's Encrypt o auto-signed para dev)
    - Configurar WebSocket upgrade para rutas `/ws/agent/*` y `/ws/spa/*`
    - Configurar proxy_pass a Uvicorn backend
    - Habilitar per-message-deflate para compresión WebSocket
    - Configurar servido de archivos estáticos del SPA con caché
    - _Requirements: 13.5, 2.6_

- [ ] 14. Frontend SPA (HTMX + Alpine.js)
  - [ ] 14.1 Crear estructura base del Frontend SPA
    - Crear directorio `frontend/` con estructura de archivos HTML
    - Implementar layout principal con HTMX y Alpine.js (sin build step)
    - Implementar página de login con formulario de autenticación
    - Implementar manejo de sesión JWT (almacenamiento en memoria, auto-logout 30min inactividad)
    - Implementar indicador visual de estado de conexión WebSocket
    - _Requirements: 6.1, 6.7, 6.8_

  - [ ] 14.2 Implementar panel de control del operador
    - Implementar visualización de estado en tiempo real: cámara activa, tally, timecode, estado de pipelines
    - Implementar inyección de notas manuales via formulario
    - Implementar campo de prompts de IA
    - Implementar Panic_Button con confirmación visual
    - Implementar selector de Backend_IA (Bedrock/Local)
    - Implementar configuración de sesión (crear, pausar, finalizar)
    - Conectar via WebSocket con actualizaciones <200ms de latencia visual
    - _Requirements: 6.2, 6.3, 6.4, 6.5_

  - [ ] 14.3 Implementar reconexión y degradación graceful del SPA
    - Implementar reconexión WebSocket: reintentos cada 3s, máximo 10 intentos
    - Deshabilitar controles de acción durante desconexión
    - Mostrar indicador visual de desconexión
    - Solicitar reconexión manual tras agotar reintentos
    - _Requirements: 6.8_

- [ ] 15. Checkpoint - Verificar backend y frontend
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. Agente_Local refactorizado (sin PyQt6)
  - [ ] 16.1 Refactorizar Agente_Local como proceso autónomo
    - Crear módulo `switch_bot/web/agent_main.py` como entrypoint del agente
    - Integrar AgentWebSocketClient con FallbackManager y StateSyncProtocol
    - Integrar HeartbeatManager del lado cliente
    - Mantener interfaz existente de CaptureManager e InferenceEngine sin cambios
    - Eliminar dependencias de PyQt6 del agente
    - Implementar indicadores de tally para estado de conectividad (conectado/reconectando/fallback)
    - Actualizar indicador dentro de 1s desde cambio de estado
    - _Requirements: 1.2, 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.6, 14.1, 14.2_

  - [ ] 16.2 Implementar lógica de Motor_Decisión local para Modo Fallback
    - Implementar `LocalDecisionEngine` que toma decisiones basándose en gaze + VAD
    - Usar último mapeo personaje-cámara conocido (sin enriquecimiento semántico)
    - Garantizar ciclo captura-inferencia-envío dentro del frame time (16.67ms@60fps, 33.33ms@30fps)
    - Descartar frames retrasados y registrar frame drop en log local
    - _Requirements: 3.5, 3.7, 4.2_

  - [ ] 16.3 Escribir unit tests para Agente_Local refactorizado
    - Test que agente opera sin PyQt6
    - Test activación/desactivación de fallback via heartbeat timeout
    - Test indicadores de tally actualizan en <1s
    - Test Motor_Decisión local toma decisiones solo con gaze + VAD
    - _Requirements: 1.4, 4.1, 4.2, 4.6_

- [ ] 17. Logs y metadata centralizados
  - [ ] 17.1 Implementar pipeline de logs y metadata en el servidor
    - Adaptar Pipeline_Metadata para almacenar eventos con SMPTE_TC original + timestamp de recepción ISO 8601
    - Mantener integridad temporal ordenando por SMPTE_TC independientemente del orden de recepción
    - Almacenar archivos .jsonl, .edl, .drp en almacenamiento persistente que sobreviva reinicios
    - Implementar consolidación de artefactos al finalizar sesión (disponible en <60s)
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ] 17.2 Escribir unit tests para pipeline de logs centralizados
    - Test eventos se almacenan con doble timestamp (SMPTE_TC + ISO 8601)
    - Test orden por SMPTE_TC se mantiene ante recepción desordenada
    - Test retransmisión de eventos post-reconexión preserva SMPTE_TC original
    - _Requirements: 9.3, 9.4, 9.6_

- [ ] 18. Checkpoint - Verificar agente refactorizado y logs
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Compatibilidad con tests existentes
  - [ ] 19.1 Verificar y adaptar interfaces públicas para compatibilidad con 605 tests
    - Verificar que Coordinador, Motor_Decisión, Filtro_Histéresis mantienen interfaces públicas idénticas
    - Verificar que CaptureManager e InferenceEngine mantienen firmas sin cambios
    - Verificar que Pipeline_Metadata produce .jsonl byte-a-byte idénticos
    - Verificar que Motor_EDL produce EDL CMX 3600 byte-a-byte idénticos
    - Asegurar que errores de comunicación se propagan como excepciones locales equivalentes
    - Ejecutar suite completa de 605 tests y verificar 0 fallos / 0 errores nuevos
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_

  - [ ] 19.2 Escribir integration tests para comunicación agente-servidor
    - Test flujo completo: agente envía inferencia → servidor procesa → servidor envía comando → agente ejecuta
    - Test reconexión con State_Sync: desconexión → fallback → reconexión → sync exitoso
    - Test multi-operador: 4 agentes conectados simultáneamente sin interferencia
    - Test SPA recibe actualizaciones de estado en tiempo real
    - _Requirements: 2.1, 2.2, 2.9, 4.4, 4.5, 15.1, 15.4_

- [ ] 20. Final checkpoint - Suite completa de tests
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Unit tests validate specific examples and edge cases
- Integration tests validate end-to-end communication flows
- Property-based tests (tasks 21.5–21.13) validan las 9 Correctness Properties del diseño para Requisito 16 (UserStore)
- La implementación es en Python 3.11+ con FastAPI, pytest y hypothesis
- Se preserva compatibilidad total con los 605 tests existentes del monolito
- Dependencia adicional requerida: `passlib[bcrypt]` para hashing de contraseñas

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["5.2", "6.1"] },
    { "id": 6, "tasks": ["6.2", "8.1"] },
    { "id": 7, "tasks": ["8.2", "9.1"] },
    { "id": 8, "tasks": ["9.2", "10.1"] },
    { "id": 9, "tasks": ["10.2", "21.1"] },
    { "id": 10, "tasks": ["21.2"] },
    { "id": 11, "tasks": ["21.3", "21.4"] },
    { "id": 12, "tasks": ["21.5", "21.6", "21.7", "21.8", "21.9"] },
    { "id": 13, "tasks": ["21.10", "21.11", "21.12", "21.13"] },
    { "id": 14, "tasks": ["21.14", "12.1"] },
    { "id": 15, "tasks": ["12.2", "12.3", "13.1"] },
    { "id": 16, "tasks": ["12.4", "14.1"] },
    { "id": 17, "tasks": ["14.2", "14.3", "16.1"] },
    { "id": 18, "tasks": ["16.2", "16.3", "17.1"] },
    { "id": 19, "tasks": ["17.2", "19.1"] },
    { "id": 20, "tasks": ["19.2"] }
  ]
}
```
