"""Strategy modules. Each exposes DEFAULT_PARAMS (dict) and generate_signals(m1: DataFrame, **params) -> Signals."""
import importlib


def load(name: str):
    return importlib.import_module(f"strategies.{name}")
