"""API dependencies."""
from ..core.analyzer import get_analyzer, LevelAnalyzer
from ..core.generator import get_generator, LevelGenerator
from ..core.simulator import get_simulator, LevelSimulator
from ..clients.gboost import get_gboost_client, GBoostClient


def get_level_analyzer() -> LevelAnalyzer:
    """Dependency for level analyzer."""
    return get_analyzer()


def get_level_generator() -> LevelGenerator:
    """Dependency for level generator."""
    return get_generator()


def get_level_simulator() -> LevelSimulator:
    """Dependency for level simulator."""
    return get_simulator()


def get_gboost() -> GBoostClient:
    """Dependency for GBoost client."""
    return get_gboost_client()
