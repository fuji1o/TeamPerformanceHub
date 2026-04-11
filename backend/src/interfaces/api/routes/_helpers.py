"""Вспомогательные функции для роутеров"""
from typing import List, Optional, Dict
from src.interfaces.api.schemas.response import SignalBox


def safe_avg(values: List[Optional[float]], default: float = 0) -> float:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else default


def to_signal(value: Optional[float], metric: str) -> SignalBox:
    thresholds = {
        "commits_per_week": {
            "good": 5, "warning": 2,
            "label": "Активность коммитов",
            "hints": {
                "good": "Регулярная активность",
                "warning": "Можно чаще",
                "bad": "Мало коммитов"
            }
        },
        "review_delay_hours": {
            "good": 4, "warning": 24,
            "label": "Скорость ревью",
            "inverse": True,
            "hints": {
                "good": "Быстрая обратная связь",
                "warning": "Ревью с задержкой",
                "bad": "Долгое ожидание ревью"
            }
        },
        "mr_description_length": {
            "good": 100, "warning": 20,
            "label": "Описание MR",
            "hints": {
                "good": "Подробные описания",
                "warning": "Можно подробнее",
                "bad": "Нет описаний"
            }
        },
    }
    
    cfg = thresholds.get(metric, {"label": metric, "good": 0, "warning": 0, "hints": {}})
    hints = cfg.get("hints", {})
    
    if value is None:
        return SignalBox(
            label=cfg["label"],
            status="neutral",
            hint="Нет данных"
        )
    
    is_inverse = cfg.get("inverse", False)
    
    if is_inverse:
        if value <= cfg["good"]:
            return SignalBox(label=cfg["label"], status="good", hint=hints.get("good", ""))
        if value <= cfg["warning"]:
            return SignalBox(label=cfg["label"], status="warning", hint=hints.get("warning", ""))
        return SignalBox(label=cfg["label"], status="bad", hint=hints.get("bad", ""))
    else:
        if value >= cfg["good"]:
            return SignalBox(label=cfg["label"], status="good", hint=hints.get("good", ""))
        if value >= cfg["warning"]:
            return SignalBox(label=cfg["label"], status="warning", hint=hints.get("warning", ""))
        return SignalBox(label=cfg["label"], status="bad", hint=hints.get("bad", ""))