---
inclusion: auto
---

# Convenciones Python — Switch_bot

## Versión y Typing

- Python 3.11+ es el mínimo requerido.
- Usar type hints en TODAS las firmas de funciones y métodos.
- Usar `from __future__ import annotations` en todos los módulos para forward references.
- Preferir `X | None` sobre `Optional[X]` y `list[X]` sobre `List[X]`.

## Estructura de Módulos

```
switch_bot/
├── ia/                  # Backend de IA (Strategy pattern)
│   ├── __init__.py
│   ├── backend_base.py  # IABackend ABC
│   ├── backend_config.py# IABackendConfig dataclass
│   ├── bedrock_backend.py
│   ├── local_backend.py
│   ├── ia_enricher.py   # IAEnricher (orquestador)
│   ├── model_catalog.py # IAModelInfo, IAModelCatalog
│   └── enrichment_result.py
├── models/              # Data models (frozen dataclasses)
├── serializers/         # EDL, DRP serialization
├── engines/             # Decision, Hysteresis, Panic, ScriptParser
├── pipelines/           # ATEM, OBS, Metadata, EDL pipelines
├── capture/             # Video/Audio capture (multiprocessing)
├── inference/           # MediaPipe, VAD
└── gui/                 # PyQt6 GUI
```

## Async/Await

- Todas las operaciones de red (Bedrock, Ollama, OBS WebSocket, ATEM TCP) deben ser `async`.
- Usar `asyncio.gather(*tasks, return_exceptions=True)` para dispatch paralelo a pipelines.
- Usar `asyncio.wait_for(coro, timeout=seconds)` para timeouts estrictos en backends de IA.
- No mezclar `asyncio.run()` dentro de un event loop activo — usar `loop.run_in_executor()` para código sync legacy.

## Dataclasses

- Modelos de datos inmutables: usar `@dataclass(frozen=True)` para `SMPTETimecode`, `EnrichedPayload`, `EnrichmentResult`.
- Modelos de configuración: usar `@dataclass` mutable con validación en `__post_init__`.
- Preferir `field(default_factory=list)` sobre listas mutables como default.

## Error Handling

- Definir excepciones específicas por dominio: `ScriptFormatError`, `BackendConnectionError`, `BackendTimeoutError`, `ModelDiscoveryError`.
- Nunca atrapar `Exception` genérico sin re-raise o logging.
- Usar `logging.getLogger(__name__)` en cada módulo — logging estructurado JSON para producción.

## Testing

- Tests de propiedades con Hypothesis: un archivo por propiedad en `tests/property/`.
- Tests unitarios en `tests/unit/`, integración en `tests/integration/`.
- Nombres de tests: `test_{módulo}_{comportamiento_esperado}`.
- Usar `@pytest.mark.asyncio` para tests de funciones async.
- Mocks: usar `unittest.mock.AsyncMock` para backends de IA en tests unitarios.
