from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime

from src.domain.analytics import GitLabAnalyticsComplete, MultiProjectAnalytics
from src.infrastructure.project_manager import ProjectManager
from src.interfaces.api.routes._helpers import get_all_contributors

router = APIRouter(tags=["overview"])
project_manager = ProjectManager()


@router.get("/api/overview")
async def get_overview(
    days: int = Query(30, ge=7, le=365),
    project_id: Optional[int] = Query(None)
):
    """
    Общий обзор активности.
    Возвращает сводку без привязки к конкретному разработчику.
    """
    if project_id:
        analytics = GitLabAnalyticsComplete(project_id=project_id)
        report = await analytics.generate_full_report(days=days)
        projects_info = None
        projects_count = 1
        mrs_list = report['merge_requests']['list']
        total_comments = report.get('comments', {}).get('total_comments', 0)
    else:
        projects = await project_manager.get_all_projects()
        project_ids = [p['id'] for p in projects]
        
        if not project_ids:
            return {
                "period_days": days,
                "project_id": None,
                "generated_at": datetime.now().isoformat(),
                "totals": {"commits": 0, "merge_requests": 0, "developers": 0, "projects": 0, "total_comments": 0},
                "all_contributors": [],
                "projects_breakdown": {},
                "merge_requests": {"list": []}
            }
        
        multi = MultiProjectAnalytics(project_ids=project_ids)
        report = await multi.generate_aggregated_report(days=days)
        projects_info = report.get('projects', {})
        projects_count = len(projects_info)
        mrs_list = report['merge_requests']['list']
        total_comments = sum(mr.get('comment_stats', {}).get('total', 0) for mr in mrs_list)
    
    commits = report.get('commits', {})
    
    # Получаем всех разработчиков (не только топ)
    all_contributors = []
    for author_name, stats in commits.get('by_author', {}).items():
        if isinstance(stats, dict):
            all_contributors.append({
                "name": author_name,
                "commits": stats.get('commits', 0),
                "additions": stats.get('additions', 0),
                "deletions": stats.get('deletions', 0)
            })
        else:
            all_contributors.append({
                "name": author_name,
                "commits": stats,
                "additions": 0,
                "deletions": 0
            })
    
    all_contributors.sort(key=lambda x: x['commits'], reverse=True)
    
    merged_mrs = len([m for m in mrs_list if m.get('state') == 'merged'])
    merge_times = [
        m.get('time_to_merge_hours')
        for m in mrs_list
        if m.get('state') == 'merged' and m.get('time_to_merge_hours') is not None
    ]
    avg_merge_time = sum(merge_times) / len(merge_times) if merge_times else None
    
    return {
        "period_days": days,
        "project_id": project_id,
        "generated_at": report.get('generated_at', datetime.now().isoformat()),
        "totals": {
            "commits": commits.get('total', 0),
            "merge_requests": len(mrs_list),
            "merged_merge_requests": merged_mrs,
            "avg_merge_time_hours": avg_merge_time,
            "developers": len(commits.get('by_author', {})),
            "projects": projects_count,
            "total_comments": total_comments,
        },
        "all_contributors": all_contributors,
        "merge_requests": {
            "list": mrs_list
        },
        "projects_breakdown": projects_info,
        "review_activity": report.get('review_activity', {}),
        "size_distribution": report.get('size_distribution', {}),
        "tests_ratio": report.get('tests_ratio', {}),
        "wip_stale": report.get('wip_stale', {}),
    }