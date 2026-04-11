from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any


class ProjectInfo(BaseModel):
    id: int
    name: str
    full_path: str
    web_url: str
    namespace: str


class ProjectListResponse(BaseModel):
    projects: List[ProjectInfo]
    total: int


class SignalBox(BaseModel):
    label: str
    status: str = Field(..., pattern="^(good|warning|bad|neutral)$")
    hint: str


class MRQualitySignals(BaseModel):
    small_size: bool
    has_description: bool
    minimal_rework: bool
    has_review_discussion: bool
    quick_first_review: Optional[bool] = None


class MRQualityDetails(BaseModel):
    changes_count: int
    additions: int = 0
    deletions: int = 0 
    description_length: int
    description_preview: Optional[str]
    iterations_count: int
    comments_count: int
    created_at: str
    merged_at: Optional[str] = None


class MRQualityScore(BaseModel):
    signals: MRQualitySignals
    details: MRQualityDetails
    quality_ratio: float = Field(..., ge=0, le=1)


class MRItem(BaseModel):
    iid: int
    title: str
    state: str
    web_url: str
    created_at: str
    merged_at: Optional[str] = None
    time_to_merge_hours: Optional[float] = None
    commits_count: int = 0
    author: str
    author_username: str
    actual_author: str
    actual_author_username: Optional[str] = None
    merged_by: Optional[str] = None
    merged_by_username: Optional[str] = None
    quality_score: MRQualityScore
    comment_stats: Dict[str, Any]
    project_id: Optional[int] = None
    project_name: Optional[str] = None


class DeveloperReportResponse(BaseModel):
    developer: str
    period_days: int
    generated_at: str
    project_id: Optional[int] = None
    project_name: str
    summary_signals: List[SignalBox]
    commits: Dict[str, Any]
    merge_requests: List[MRItem]
    mr_stats: Dict[str, Any]
    comments: Dict[str, Any]
    conversation_prompt: str


# ═══════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════

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


def get_all_contributors(by_author: Dict) -> List[Dict]:
    """Все пользователи"""
    sorted_authors = sorted(
        by_author.items(),
        key=lambda x: x[1].get('commits', 0) if isinstance(x[1], dict) else x[1],
        reverse=True
    )
    return [
        {"name": name, "commits": stats.get('commits', stats) if isinstance(stats, dict) else stats}
        for name, stats in sorted_authors
    ]