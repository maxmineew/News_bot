from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Article:
    title: str
    url: str
    published: datetime  # aware, UTC
    source: str
    topic: str
    summary: str = ""
    weight: float = 1.0
    foreign: bool = False      # оригинал не на русском
    translated: bool = False   # перевод выполнен
