from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime
from analytics import GitLabAnalyticsComplete

app = FastAPI(
    title="Team Performance Hub",
    description="Дашборд активности разработчиков на основе GitLab"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # API автор
    author: str
    author_username: str
    # Реальный автор (по коммитам)
    actual_author: str
    actual_author_username: Optional[str] = None
    # Кто смержил
    merged_by: Optional[str] = None
    merged_by_username: Optional[str] = None
    quality_score: MRQualityScore
    comment_stats: Dict[str, Any]


class DeveloperReportResponse(BaseModel):
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


def generate_conversation_prompt(signals: List[SignalBox]) -> str:
    bad = [s.label for s in signals if s.status == "bad"]
    warn = [s.label for s in signals if s.status == "warning"]
    
    if bad:
        return f"🔴 Обратите внимание: {', '.join(bad)}. Обсудите, есть ли блоки или нужна помощь."
    if warn:
        return f"🟡 Зоны роста: {', '.join(warn)}. Спросите, что мешает."
    return "🟢 Активность в норме. Поддержите текущий темп."


def match_author(mr: Dict, username: str) -> bool:
    """Проверяет, является ли пользователь автором MR"""
    checks = [
        mr.get('actual_author', ''),
        mr.get('actual_author_username', ''),
        mr.get('author', ''),
        mr.get('author_username', '')
    ]
    username_lower = username.lower()
    return any(
        check and username_lower in check.lower()
        for check in checks
    )

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/team/list")
async def get_team_list(days: int = Query(30, ge=7, le=365)):
    analytics = GitLabAnalyticsComplete()
    report = await analytics.generate_full_report(days=days)
    
    # Собираем всех авторов: из коммитов и из MR
    authors = set(report['commits']['by_author'].keys())
    
    for mr in report['merge_requests']['list']:
        if mr.get('actual_author'):
            authors.add(mr['actual_author'])
        if mr.get('author'):
            authors.add(mr['author'])
    
    return {"developers": sorted(authors), "period_days": days}


@app.get("/api/team/{username}/report", response_model=DeveloperReportResponse)
async def get_full_report(username: str, days: int = Query(30, ge=7, le=365)):
    analytics = GitLabAnalyticsComplete()
    report = await analytics.generate_full_report(days=days)
    
    print("[DEBUG] All authors in commits:")
    for author_name, stats in report['commits']['by_author'].items():
        print(f"  - {author_name}: {stats.get('commits', 0)} commits")
    # Ищем данные автора по коммитам (с учётом регистра)
    author_stats = None
    matched_author_name = None
    
    for author_name, stats in report['commits']['by_author'].items():
        if username.lower() in author_name.lower():
            author_stats = stats
            matched_author_name = author_name
            break
    
    if author_stats is None:
        author_stats = {'commits': 0, 'additions': 0, 'deletions': 0}
        matched_author_name = username
    
    commits_count = author_stats.get('commits', 0)
    commits_per_week = commits_count / (days / 7) if days > 0 else 0
    
    # MR по автору
    author_mrs = [mr for mr in report['merge_requests']['list'] if match_author(mr, username)]
    
    print(f"[DEBUG] User: {username}, Matched author: {matched_author_name}")
    print(f"[DEBUG] Commits: {commits_count}, MRs: {len(author_mrs)}")
    
    # Метрики для сигналов
    review_delays = [
        m['comment_stats'].get('first_comment_delay_hours')
        for m in author_mrs
        if m.get('comment_stats')
    ]
    avg_review_delay = safe_avg(review_delays) if review_delays else None
    
    desc_lengths = [len(m.get('description') or '') for m in author_mrs]
    avg_desc_length = sum(desc_lengths) / len(desc_lengths) if desc_lengths else None
    
    summary_signals = [
        to_signal(commits_per_week if commits_count > 0 else None, "commits_per_week"),
        to_signal(avg_review_delay, "review_delay_hours"),
        to_signal(avg_desc_length, "mr_description_length"),
    ]
    
    # Формируем список MR
    mr_items = []
    for mr in author_mrs:
        quality = mr.get('quality_score', {})
        signals_raw = quality.get('signals', {})
        details_raw = quality.get('details', {})
        
        comment_stats = mr.get('comment_stats', {})
        delay = comment_stats.get('first_comment_delay_hours')
        quick_review = delay < 24 if delay is not None else None
        
        mr_items.append(MRItem(
            iid=mr['iid'],
            title=mr['title'],
            state=mr['state'],
            web_url=mr['web_url'],
            created_at=mr['created_at'],
            merged_at=mr.get('merged_at'),
            time_to_merge_hours=mr.get('time_to_merge_hours'),
            commits_count=mr.get('commits_count', 0),
            author=mr.get('author', ''),
            author_username=mr.get('author_username', ''),
            actual_author=mr.get('actual_author', ''),
            actual_author_username=mr.get('actual_author_username'),
            merged_by=mr.get('merged_by'),
            merged_by_username=mr.get('merged_by_username'),
            quality_score=MRQualityScore(
                signals=MRQualitySignals(
                    small_size=signals_raw.get('small_size', False),
                    has_description=signals_raw.get('has_description', False),
                    minimal_rework=signals_raw.get('minimal_rework', False),
                    has_review_discussion=signals_raw.get('has_review_discussion', False),
                    quick_first_review=quick_review,
                ),
                details=MRQualityDetails(
                    changes_count=details_raw.get('changes_count', 0),
                    additions=details_raw.get('additions', 0), 
                    deletions=details_raw.get('deletions', 0),   
                    description_length=details_raw.get('description_length', 0),
                    description_preview=details_raw.get('description_preview'),
                    iterations_count=details_raw.get('iterations', 0),
                    comments_count=details_raw.get('comments_count', 0),
                    created_at=details_raw.get('created_at', mr['created_at']),
                    merged_at=mr.get('merged_at'),
                ),
                quality_ratio=quality.get('quality_ratio', 0),
            ),
            comment_stats=comment_stats
        ))
    
    # Статистика MR
    total_mrs = len(author_mrs)
    merged_mrs = len([m for m in author_mrs if m['state'] == 'merged'])
    opened_mrs = len([m for m in author_mrs if m['state'] == 'opened'])
    closed_mrs = len([m for m in author_mrs if m['state'] == 'closed'])
    
    merge_times = [
        m['time_to_merge_hours']
        for m in author_mrs
        if m.get('time_to_merge_hours') is not None
    ]
    avg_merge_time = sum(merge_times) / len(merge_times) if merge_times else None
    
    # Статистика комментариев
    total_comments = 0
    by_type: Dict[str, int] = {}
    by_author: Dict[str, int] = {}
    
    for mr in author_mrs:
        cs = mr.get('comment_stats', {})
        total_comments += cs.get('total', 0)
        
        for t, c in cs.get('by_type', {}).items():
            by_type[t] = by_type.get(t, 0) + c
        
        for a, c in cs.get('by_author', {}).items():
            by_author[a] = by_author.get(a, 0) + c
    
    return DeveloperReportResponse(
        developer=username,
        period_days=days,
        generated_at=report['generated_at'],
        project_name=report['project_name'],
        summary_signals=summary_signals,
        commits={
            'total': commits_count,
            'by_author': {matched_author_name: author_stats},
            'total_additions': author_stats.get('additions', 0),
            'total_deletions': author_stats.get('deletions', 0),
            'activity_by_hour': report['commits'].get('activity_by_hour', {}),
            'activity_by_weekday': report['commits'].get('activity_by_weekday', {})
        },
        merge_requests=mr_items,
        mr_stats={
            'total': total_mrs,
            'opened': opened_mrs,
            'merged': merged_mrs,
            'closed': closed_mrs,
            'avg_time_to_merge_hours': avg_merge_time,
            'authors': {username: total_mrs}
        },
        comments={
            'total_comments': total_comments,
            'by_type': by_type,
            'by_author': by_author,
            'per_mr_avg': total_comments / total_mrs if total_mrs > 0 else 0
        },
        conversation_prompt=generate_conversation_prompt(summary_signals)
    )