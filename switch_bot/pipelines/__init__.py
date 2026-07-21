"""Pipelines de ejecución cuádruple (ATEM, OBS, Metadata, EDL)."""

from switch_bot.pipelines.atem_pipeline import ATEMPipeline
from switch_bot.pipelines.base import Pipeline
from switch_bot.pipelines.dispatcher import DispatchResult, QuadDispatcher
from switch_bot.pipelines.edl_pipeline import EDLPipeline
from switch_bot.pipelines.metadata_pipeline import MetadataPipeline
from switch_bot.pipelines.obs_pipeline import OBSPipeline

__all__ = [
    "ATEMPipeline",
    "EDLPipeline",
    "MetadataPipeline",
    "OBSPipeline",
    "Pipeline",
    "QuadDispatcher",
    "DispatchResult",
]
