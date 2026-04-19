from fastapi import APIRouter, Query, HTTPException
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio

from src.interfaces.api.schemas.response import (
    DeveloperReportResponse, SignalBox, MRItem, MRQualityScore,
    MRQualitySignals, MRQualityDetails
)
from src.domain.analytics import GitLabAnalyticsComplete, MultiProjectAnalytics
from src.infrastructure.project_manager import ProjectManager
from src.domain.user_mapper import UserMapper
from src.domain.llm_analyzer import SimpleAnalyzer
from src.infrastructure.progress_logger import progress, info as pinfo
from . import _helpers

router = APIRouter(tags=["team"])

user_mapper = UserMapper()
project_manager = ProjectManager()


def match_author(mr: Dict, username: str) -> bool:
    """Проверяет, является ли пользователь автором MR с учётом mapping"""
    mr_actual = user_mapper.normalize_author(mr.get('actual_author', ''))
    mr_author = user_mapper.normalize_author(mr.get('author', ''))
    target = user_mapper.normalize_author(username)
    return target.lower() == mr_actual.lower() or target.lower() == mr_author.lower()


@router.get("/api/team/list")
async def get_team_list(
    days: int = Query(30, ge=7, le=365),
    project_id: Optional[int] = Query(None, description="ID проекта или None для всех")
):
    """
    Список разработчиков.
    - project_id=None — по всем проектам
    - project_id=123 — только по конкретному проекту
    """
    if project_id:
        analytics = GitLabAnalyticsComplete(project_id=project_id)
        report = await analytics.generate_full_report(days=days)
    else:
        projects = await project_manager.get_all_projects()
        project_ids = [p['id'] for p in projects]
        
        if not project_ids:
            return {"developers": [], "period_days": days, "project_id": None}
        
        multi = MultiProjectAnalytics(project_ids=project_ids)
        report = await multi.generate_aggregated_report(days=days)
    
    authors = set()
    
    for author_name in report['commits']['by_author'].keys():
        normalized = user_mapper.normalize_author(author_name)
        authors.add(normalized)
    
    mrs_list = report.get('merge_requests', {})
    if isinstance(mrs_list, dict):
        mrs_list = mrs_list.get('list', [])
    
    for mr in mrs_list:
        if mr.get('actual_author'):
            authors.add(user_mapper.normalize_author(mr['actual_author']))
        if mr.get('author'):
            authors.add(user_mapper.normalize_author(mr['author']))
    
    return {
        "developers": sorted(authors),
        "period_days": days,
        "project_id": project_id
    }


@router.get("/api/team/{username}/report", response_model=DeveloperReportResponse)
async def get_full_report(
    username: str,
    days: int = Query(30, ge=7, le=365),
    project_id: Optional[int] = Query(None, description="ID проекта или None для всех")
):
    """
    Отчёт по разработчику.
    - project_id=None — агрегация по всем проектам
    - project_id=123 — только один проект
    """
    target_username = user_mapper.normalize_author(username)
    
    if project_id:
        analytics = GitLabAnalyticsComplete(project_id=project_id)
        report = await analytics.generate_full_report(days=days)
        project_name = report.get('project_name', 'Unknown')
        all_mrs = report['merge_requests']['list']
        commits_by_author = report['commits']['by_author']
    else:
        projects = await project_manager.get_all_projects()
        project_ids = [p['id'] for p in projects]
        
        if not project_ids:
            raise HTTPException(status_code=404, detail="No projects available")
        
        multi = MultiProjectAnalytics(project_ids=project_ids)
        report = await multi.generate_aggregated_report(days=days)
        project_name = "All Projects"
        all_mrs = report['merge_requests']['list']
        commits_by_author = report['commits']['by_author']
    
    # Ищем данные автора по коммитам
    author_stats = None
    matched_author_name = None
    
    for author_name, stats in commits_by_author.items():
        normalized = user_mapper.normalize_author(author_name)
        if normalized == target_username:
            author_stats = stats
            matched_author_name = author_name
            break
    
    if author_stats is None:
        author_stats = {'commits': 0, 'additions': 0, 'deletions': 0}
        matched_author_name = target_username
    
    commits_count = author_stats.get('commits', 0)
    commits_per_week = commits_count / (days / 7) if days > 0 else 0
    author_activity_by_date = author_stats.get('activity_by_date', {})
    
    # Фильтруем MR по автору
    author_mrs = []
    for mr in all_mrs:
        if match_author(mr, target_username):
            author_mrs.append(mr)
    
    # Метрики для сигналов
    review_delays = [
        m['comment_stats'].get('first_comment_delay_hours')
        for m in author_mrs
        if m.get('comment_stats') and m['comment_stats'].get('first_comment_delay_hours') is not None
    ]
    avg_review_delay = _helpers.safe_avg(review_delays) if review_delays else None
    
    desc_lengths = [len(m.get('description') or '') for m in author_mrs]
    avg_desc_length = sum(desc_lengths) / len(desc_lengths) if desc_lengths else None
    
    summary_signals = [
        _helpers.to_signal(commits_per_week if commits_count > 0 else None, "commits_per_week"),
        _helpers.to_signal(avg_review_delay, "review_delay_hours"),
        _helpers.to_signal(avg_desc_length, "mr_description_length"),
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
            comment_stats=comment_stats,
            project_id=mr.get('project_id'),
            project_name=mr.get('project_name')
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

    commit_messages = report['commits'].get('commit_messages', {}).get(matched_author_name, [])
    analyzer = SimpleAnalyzer()
    if commit_messages:
        async with progress(f"LLM: checking {len(commit_messages)} commit messages (parallel)"):
            results = await asyncio.gather(*[
                asyncio.to_thread(analyzer.check_conventional_commit, msg)
                for msg in commit_messages
            ])
            conventional_count = sum(1 for r in results if r.get('is_conventional'))
            pinfo(f"conventional: {conventional_count}/{len(commit_messages)}")
    else:
        conventional_count = 0

    conventional_ratio = int(conventional_count / len(commit_messages) * 100) if commit_messages else 0
    async with progress("LLM: generating summary"):
        conversation_prompt = await asyncio.to_thread(
            analyzer.generate_summary,
            target_username,
            conventional_ratio,
            commits_count,
            conventional_count,
        )
    
    return DeveloperReportResponse(
        developer=target_username,
        period_days=days,
        generated_at=report['generated_at'],
        project_id=project_id,
        project_name=project_name,
        summary_signals=summary_signals,
        commits={
            'total': commits_count,
            'by_author': {matched_author_name: author_stats},
            'total_additions': author_stats.get('additions', 0),
            'total_deletions': author_stats.get('deletions', 0),
            'activity_by_hour': report['commits'].get('activity_by_hour', {}),
            'activity_by_weekday': report['commits'].get('activity_by_weekday', {}),
            'activity_by_date': author_activity_by_date
        },
        merge_requests=mr_items,
        mr_stats={
            'total': total_mrs,
            'opened': opened_mrs,
            'merged': merged_mrs,
            'closed': closed_mrs,
            'avg_time_to_merge_hours': avg_merge_time,
            'authors': {target_username: total_mrs}
        },
        comments={
            'total_comments': total_comments,
            'by_type': by_type,
            'by_author': by_author,
            'per_mr_avg': total_comments / total_mrs if total_mrs > 0 else 0
        },
        conversation_prompt=conversation_prompt
    )