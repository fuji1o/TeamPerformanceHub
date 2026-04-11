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