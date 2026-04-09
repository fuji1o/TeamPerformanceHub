from pydantic import BaseModel, Field
from typing import Optional, List, Any
from enum import Enum

class SignalStatus(str, Enum):
    GOOD = "good"
    WARNING = "warning"
    BAD = "bad"

class SignalBox(BaseModel):
    """Качественный сигнал: есть/нет + подсказка"""
    label: str = Field(..., description="Название метрики")
    status: SignalStatus = Field(..., description="Статус сигнала")
    hint: str = Field(..., description="Пояснение для разговора")
    value: Optional[float] = Field(None, description="Числовое значение")

class MRQualitySignals(BaseModel):
    """Бинарные сигналы качества MR"""
    small_size: bool = Field(..., description="MR < 500 строк")
    has_description: bool = Field(..., description="Описание > 20 символов")
    minimal_rework: bool = Field(..., description="≤ 2 итерации")
    has_review_discussion: bool = Field(..., description="Были комментарии")
    quick_first_review: Optional[bool] = Field(None, description="Первый комментарий < 24ч")

class MRQualityDetails(BaseModel):
    """Сырые данные для детального отображения"""
    changes_count: int
    description_length: int
    description_preview: Optional[str]
    iterations_count: int
    comments_count: int
    created_at: str
    merged_at: Optional[str]

class MRQualityScore(BaseModel):
    """Оценка качества MR: сигналы + детали"""
    signals: MRQualitySignals
    details: MRQualityDetails
    quality_ratio: float = Field(..., ge=0, le=1, description="Доля «зелёных» сигналов")

class MRItem(BaseModel):
    """Элемент списка MR для фронтенда"""
    iid: int
    title: str
    state: str
    web_url: str
    created_at: str
    merged_at: Optional[str] = None
    quality_score: MRQualityScore
    comment_stats: Dict[str, Any]

class DeveloperReportResponse(BaseModel):
    """Ответ для дашборда разработчика"""
    developer: str
    period_days: int
    generated_at: str
    project_name: str
    summary_signals: List[SignalBox]
    commits: Dict[str, Any]
    merge_requests: List[MRItem]
    mr_stats: Dict[str, Any]
    comments: Dict[str, Any]
    conversation_prompt: str