"""NER Wrapper abstraction layer for swappable NER backends."""

from src.pipeline.NERWrappers.UndertheseaNER import UndertheseaNER


__all__ = ["UndertheseaNER"]
