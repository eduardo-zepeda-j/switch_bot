"""Módulo de backend de IA multi-proveedor (Patrón Strategy).

Contiene la interfaz abstracta IABackend y las implementaciones:
- BedrockBackend (AWS Bedrock — Titan Embeddings V2 + Claude 3.5)
- LocalBackend (Ollama / llama.cpp / GGUF)
- IAEnricher (orquestador agnóstico al backend)
"""
