---
inclusion: auto
---

# Directrices de Seguridad — Switch_bot

## Gestión de Credenciales

- NUNCA hardcodear credenciales AWS, tokens o secretos en el código fuente.
- Usar variables de entorno o perfiles AWS (`~/.aws/credentials`) para autenticación con Bedrock.
- La configuración persistente en `~/.switch_bot/config.json` NO debe almacenar secretos, solo IDs de modelos y preferencias.
- Validar que el archivo de configuración tenga permisos restrictivos (0600) al crearlo.

## Validación de Entrada

- Validar todos los inputs del operador (texto de notas, prompts de IA) antes de enviarlos al backend:
  - Limitar longitud máxima de prompts a 4096 caracteres.
  - Sanitizar caracteres de control y secuencias de escape.
  - No pasar input del usuario directamente como instrucciones de sistema al LLM.
- Validar rutas de archivos de guión (PDF/MD/JSON) contra path traversal antes de cargar.
- Validar que los archivos de guión no excedan un tamaño máximo razonable (50 MB).

## Comunicación de Red

- Las conexiones a Ollama local deben validar que apuntan a localhost o a una IP explícitamente configurada por el operador.
- Las conexiones WebSocket a OBS y TCP a ATEM deben usar timeouts estrictos para prevenir conexiones colgadas.
- No exponer puertos de servicio al exterior sin que el operador lo configure explícitamente.
- Usar TLS cuando sea posible para conexiones remotas (Bedrock ya usa HTTPS vía boto3).

## Manejo de Datos Sensibles

- Los logs de sesión (.jsonl) pueden contener contenido de producción — no enviar logs completos a servicios externos sin consentimiento del operador.
- El contenido del guión es propiedad intelectual — las vectorizaciones se almacenan en memoria volátil, no se persisten en disco.
- Al finalizar la sesión, los vectores en memoria deben liberarse explícitamente (`del` + garbage collection).

## Ejecución Segura de Modelos Locales

- Verificar la integridad del runtime local (Ollama) antes de enviar datos: validar que responde en el endpoint esperado.
- No ejecutar binarios de modelos descargados automáticamente — el operador debe gestionar los modelos manualmente vía Ollama.
- Los modelos GGUF referenciados por llama.cpp deben ser archivos regulares en un directorio configurado, no symlinks a ubicaciones arbitrarias.

## Dependencias

- Fijar versiones de dependencias críticas de seguridad (boto3, httpx, aiohttp).
- No instalar paquetes de fuentes no verificadas para backends de IA.
- Usar `pip audit` o `safety check` periódicamente para detectar vulnerabilidades conocidas.

## Manejo de Errores

- Los mensajes de error mostrados al operador NO deben exponer stack traces, rutas internas del sistema, ni credenciales parciales.
- Los errores de conexión a backends deben reportar solo: tipo de backend, host/puerto, y causa general (timeout, rechazo, autenticación).
- Usar logging estructurado con niveles apropiados — nunca log a nivel DEBUG en producción.
