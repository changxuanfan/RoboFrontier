"""Repository root and the MJCF vector formatter shared by the scene builders."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def vector(values):
    return " ".join(str(float(x)) for x in values)

