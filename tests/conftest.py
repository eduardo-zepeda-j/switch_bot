"""Configuración global de pytest y Hypothesis para el proyecto Switch_bot."""

import os

from hypothesis import settings, Phase, HealthCheck

# Perfil de desarrollo: ejecución rápida para iteración local
settings.register_profile(
    "dev",
    max_examples=100,
    phases=[Phase.explicit, Phase.generate, Phase.target, Phase.shrink],
    suppress_health_check=[HealthCheck.too_slow],
)

# Perfil de CI: más exhaustivo para detectar errores sutiles
settings.register_profile(
    "ci",
    max_examples=200,
    phases=[Phase.explicit, Phase.generate, Phase.target, Phase.shrink],
)

# Seleccionar perfil según variable de entorno
_profile = "ci" if os.environ.get("CI") else "dev"
settings.load_profile(_profile)
