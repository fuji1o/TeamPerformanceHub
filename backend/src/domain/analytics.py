# src/domain/analytics.py
import asyncio
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Set, Optional
from dotenv import load_dotenv
import aiohttp
from src.domain.user_mapper import UserMapper

load_dotenv()


class GitLabAnalyticsComplete:
    """Аналитика для одного проекта GitLab"""
    
    def __init__(self, project_id: Optional[int] = None):
        """
        Args:
            project_id: ID проекта или None для использования значения из .env
        """
        self.token = os.getenv("GITLAB_TOKEN", "").strip()
        self.url = os.getenv("GITLAB_URL", "https://gitlab.com").strip()
        self.user_mapper = UserMapper()
        
        if project_id is not None:
            self.project_id = str(project_id)
        else:
            self.project_id = os.getenv("GITLAB_PROJECT_ID", "").strip() or None

    def _get_auth_headers(self) -> Dict[str, str]:
        """Возвращает заголовки авторизации для GitLab API"""
        return {
            "PRIVATE-TOKEN": self.token,
            "User-Agent": "TeamPerformanceHub/1.0",
            "Content-Type": "application/json"
        }

    async def _gitlab_get(self, session: aiohttp.ClientSession, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Универсальный метод для GET-запросов к GitLab API"""
        url = f"{self.url}/api/v4{endpoint}"
        headers = self._get_auth_headers()
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    print(f"[WARN] 404: {endpoint}")
                    return None
                else:
                    error_text = await response.text()
                    print(f"[ERROR] {response.status} при запросе {endpoint}: {error_text[:200]}")
                    return None
        except Exception as e:
            print(f"[ERROR] Сетевая ошибка при запросе {endpoint}: {type(e).__name__}: {e}")
            return None

    async def _gitlab_get_paginated(self, session: aiohttp.ClientSession, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        """Получает все страницы пагинированного ответа"""
        items = []
        page = 1
        per_page = 100
        
        while True:
            current_params = {**(params or {}), "page": page, "per_page": per_page}
            data = await self._gitlab_get(session, endpoint, current_params)
            
            if not data:
                break
            
            if isinstance(data, list):
                if not data:
                    break
                items.extend(data)
                page += 1
            else:
                items.append(data)
                break
                
        return items

    async def get_project_info(self) -> Dict:
        if not self.project_id:
            return {"name": "All Projects"}
        
        async with aiohttp.ClientSession() as session:
            data = await self._gitlab_get(session, f"/projects/{self.project_id}")
            return data or {}

    async def get_all_branches(self) -> List[Dict]:
        if not self.project_id:
            return []
        
        branches = []
        async with aiohttp.ClientSession() as session:
            data = await self._gitlab_get_paginated(session, f"/projects/{self.project_id}/repository/branches")
            
            for branch in data:
                branches.append({
                    'name': branch['name'],
                    'commit': branch['commit']['short_id'],
                    'commit_date': branch['commit'].get('created_at'),
                    'protected': branch.get('protected', False),
                    'default': branch.get('default', False)
                })
        return branches

    async def get_commits_for_branch(self, branch_name: str, days: int = 90, seen_ids: Set[str] = None) -> List[Dict]:
        """Получает коммиты для ветки, исключая уже обработанные"""
        if not self.project_id:
            return []
        
        if seen_ids is None:
            seen_ids = set()
            
        commits = []
        since_date = (datetime.now() - timedelta(days=days)).isoformat()
        params = {"ref_name": branch_name, "since": since_date}
        
        async with aiohttp.ClientSession() as session:
            commits_data = await self._gitlab_get_paginated(session, f"/projects/{self.project_id}/repository/commits", params)
            
            for commit in commits_data:
                if commit['id'] in seen_ids:
                    continue
                seen_ids.add(commit['id'])

                detail = await self._gitlab_get(session, f"/projects/{self.project_id}/repository/commits/{commit['id']}")
                stats = detail.get('stats', {}) if detail else {}
                
                commit_date = datetime.fromisoformat(commit['created_at'].replace('Z', '+00:00'))
                commits.append({
                    'id': commit['id'],
                    'short_id': commit['short_id'],
                    'title': commit['title'],
                    'message': commit['message'],
                    'author_name': self.user_mapper.normalize_author(commit['author_name']),
                    'author_email': commit['author_email'],
                    'created_at': commit['created_at'],
                    'date': commit_date,
                    'hour': commit_date.hour,
                    'weekday': commit_date.weekday(),
                    'additions': stats.get('additions', 0),
                    'deletions': stats.get('deletions', 0),
                    'total_changes': stats.get('total', 0)
                })
        return commits

    def get_commit_activity_stats(self, commits: List[Dict]) -> Dict:
        if not commits:
            return {
                'total_commits': 0,
                'total_additions': 0,
                'total_deletions': 0,
                'authors': {},
                'commits_by_hour': {},
                'commits_by_weekday': {},
                'commits_by_date': defaultdict(int),    
                'commit_messages': {},
                'first_commit': None,
                'last_commit': None
            }
        
        stats = {
            'total_commits': len(commits),
            'total_additions': sum(c['additions'] for c in commits),
            'total_deletions': sum(c['deletions'] for c in commits),
            'authors': defaultdict(lambda: {'commits': 0, 'additions': 0, 'deletions': 0, 'activity_by_date': defaultdict(int)}),
            'commits_by_hour': defaultdict(int),
            'commits_by_weekday': defaultdict(int),
            'commits_by_date': defaultdict(int),
            'commit_messages': defaultdict(list),
            'first_commit': commits[-1]['created_at'] if commits else None,
            'last_commit': commits[0]['created_at'] if commits else None
        }
        
        for commit in commits:
            author = commit['author_name']
            date_str = commit['date'].date().isoformat()
            stats['authors'][author]['commits'] += 1
            stats['authors'][author]['additions'] += commit['additions']
            stats['authors'][author]['deletions'] += commit['deletions']
            stats['commit_messages'][author].append(commit.get('message', ''))
            stats['commits_by_hour'][commit['hour']] += 1
            stats['commits_by_weekday'][commit['weekday']] += 1
            stats['commits_by_date'][date_str] += 1
            stats['authors'][author]['activity_by_date'][date_str] += 1

        stats['authors'] = {k: {
            'commits': v['commits'],
            'additions': v['additions'],
            'deletions': v['deletions'],
            'activity_by_date': dict(v['activity_by_date']),
            'commit_messages': stats['commit_messages'].get(k, []) 
        } for k, v in stats['authors'].items()}
        
        stats['commits_by_hour'] = dict(stats['commits_by_hour'])
        stats['commits_by_weekday'] = dict(stats['commits_by_weekday'])
        stats['commits_by_date'] = dict(stats['commits_by_date'])
        stats['commit_messages'] = dict(stats['commit_messages']) 
        
        print(f"[DEBUG] Total commits: {stats['total_commits']}")
        print(f"[DEBUG] Authors: {list(stats['authors'].keys())}")
        for author, data in stats['authors'].items():
            print(f"[DEBUG]   {author}: {data['commits']} commits, activity_by_date: {data['activity_by_date']}")
        
        return stats

    async def get_merge_request_comments(self, mr_iid: int) -> List[Dict]:
        if not self.project_id:
            return []
        
        comments = []
        endpoint = f"/projects/{self.project_id}/merge_requests/{mr_iid}/discussions"
        
        async with aiohttp.ClientSession() as session:
            discussions = await self._gitlab_get_paginated(session, endpoint)
            
            for discussion in discussions:
                for note in discussion.get('notes', []):
                    if note.get('system', False):
                        continue
                    comment = {
                        'id': note['id'],
                        'author': self.user_mapper.normalize_author(note['author']['name']),
                        'author_username': note['author']['username'],
                        'created_at': note['created_at'],
                        'body': note['body'],
                        'type': self._classify_comment(note['body']),
                        'is_reply': note.get('type') == 'DiscussionNote',
                        'discussion_id': discussion.get('id')
                    }
                    if note.get('position'):
                        pos = note['position']
                        comment['file_path'] = pos.get('new_path') or pos.get('old_path')
                        comment['line'] = pos.get('new_line') or pos.get('old_line')
                    comments.append(comment)
                    
        return comments

    def _classify_comment(self, comment_body: str) -> str:
        body_lower = (comment_body or "").lower()
        if any(k in body_lower for k in ['lgtm', 'approve', 'good', 'одобряю', 'отлично']):
            return 'approval'
        if any(k in body_lower for k in ['архитектура', 'дизайн', 'паттерн', 'architecture']):
            return 'architectural'
        if any(k in body_lower for k in ['bug', 'fix', 'error', 'issue', 'баг', 'ошибка']):
            return 'bug'
        if any(k in body_lower for k in ['стиль', 'опечатка', 'пробел', 'nit']):
            return 'nitpick'
        if any(k in body_lower for k in ['предлагаю', 'может', 'стоит', 'лучше', 'suggest']):
            return 'suggestion'
        if any(k in body_lower for k in ['?', 'почему', 'зачем', 'как', 'что', 'question']):
            return 'question'
        return 'other'

    async def _get_mr_commits(self, mr_iid: int) -> List[Dict]:
        """Получает коммиты для конкретного MR"""
        if not self.project_id:
            return []
        
        commits = []
        endpoint = f"/projects/{self.project_id}/merge_requests/{mr_iid}/commits"
        
        async with aiohttp.ClientSession() as session:
            commits_data = await self._gitlab_get_paginated(session, endpoint)
            
            for commit in commits_data:
                commits.append({
                    'id': commit['id'],
                    'created_at': commit['created_at'],
                    'title': commit['title'],
                    'author_name': commit.get('author_name', ''),
                    'author_email': commit.get('author_email', '')
                })
        return commits

    async def get_merge_requests_detailed(self, days: int = 90) -> List[Dict]:
        if not self.project_id:
            return []
        
        since_date = (datetime.now() - timedelta(days=days)).isoformat()
        merge_requests = []
        
        async with aiohttp.ClientSession() as session:
            for state in ['opened', 'merged', 'closed']:
                params = {
                    "state": state,
                    "created_after": since_date,
                    "order_by": "updated_at",
                    "sort": "desc"
                }
                
                mrs = await self._gitlab_get_paginated(session, f"/projects/{self.project_id}/merge_requests", params)
                
                for mr in mrs:
                    created_at = datetime.fromisoformat(mr['created_at'].replace('Z', '+00:00'))
                    
                    comments, commits = await asyncio.gather(
                        self.get_merge_request_comments(mr['iid']),
                        self._get_mr_commits(mr['iid'])
                    )
                    
                    comment_stats = self._calculate_comment_stats(comments, created_at)

                    total_additions, total_deletions = 0, 0
                    for c in commits:
                        detail = await self._gitlab_get(session, f"/projects/{self.project_id}/repository/commits/{c['id']}")
                        if detail:
                            s = detail.get('stats', {})
                            total_additions += s.get('additions', 0)
                            total_deletions += s.get('deletions', 0)

                    commit_authors = set(c['author_name'] for c in commits if c.get('author_name'))
                    if commit_authors:
                        real_author = next(iter(commit_authors))
                        real_author = self.user_mapper.normalize_author(real_author)
                        real_author_username = None
                        for commit in commits:
                            if self.user_mapper.normalize_author(commit.get('author_name', '')) == real_author:
                                email = commit.get('author_email', '')
                                if email:
                                    real_author_username = email.split('@')[0]
                                break
                        if not real_author_username:
                            real_author_username = real_author.lower().replace(' ', '.')
                    else:
                        real_author = self.user_mapper.normalize_author(mr['author']['name'])
                        real_author_username = mr['author']['username']

                    merged_by = None
                    merged_by_username = None
                    if mr.get('merged_by'):
                        merged_by = mr['merged_by'].get('name')
                        merged_by_username = mr['merged_by'].get('username')
                    elif mr.get('merge_user'):
                        merged_by = mr['merge_user'].get('name')
                        merged_by_username = mr['merge_user'].get('username')
                    
                    total_changes = total_additions + total_deletions
                    mr_quality = self._calculate_mr_quality_score(
                        mr, commits, comments, total_changes, total_additions, total_deletions
                    )
                    
                    mr_data = {
                        'iid': mr['iid'],
                        'title': mr['title'],
                        'description': mr.get('description', ''),
                        'author': self.user_mapper.normalize_author(mr['author']['name']),
                        'author_username': mr['author']['username'],
                        'actual_author': real_author,
                        'actual_author_username': real_author_username,
                        'merged_by': merged_by,
                        'merged_by_username': merged_by_username,
                        'created_at': mr['created_at'],
                        'merged_at': mr.get('merged_at'),
                        'state': state,
                        'source_branch': mr['source_branch'],
                        'target_branch': mr['target_branch'],
                        'web_url': mr['web_url'],
                        'changes_count': mr.get('changes_count', 0),
                        'total_additions': total_additions,
                        'total_deletions': total_deletions,
                        'total_changes': total_changes,
                        'commits_count': len(commits),
                        'comments': comments,
                        'comment_stats': comment_stats,
                        'quality_score': mr_quality,
                        'iterations': self._count_iterations(commits, created_at),
                        'total_lines_changed': total_changes,
                        'additions': total_additions,
                        'deletions': total_deletions
                    }
                    
                    if state == 'merged' and mr.get('merged_at'):
                        merged_at = datetime.fromisoformat(mr['merged_at'].replace('Z', '+00:00'))
                        mr_data['time_to_merge_hours'] = (merged_at - created_at).total_seconds() / 3600
                    else:
                        mr_data['time_to_merge_hours'] = None
                    
                    merge_requests.append(mr_data)
        
        return merge_requests

    def _calculate_comment_stats(self, comments: List[Dict], created_at: datetime) -> Dict:
        if not comments:
            return {
                'total': 0,
                'by_type': {},
                'by_author': {},
                'participants': [],
                'first_comment_delay_hours': None,
                'reviewers_count': 0
            }
        
        by_type = defaultdict(int)
        by_author = defaultdict(int)
        participants = set()
        
        for c in comments:
            by_type[c['type']] += 1
            by_author[c['author']] += 1
            participants.add(c['author'])
        
        first_comment = min(comments, key=lambda x: x['created_at'])
        first_time = datetime.fromisoformat(first_comment['created_at'].replace('Z', '+00:00'))
        delay_hours = round((first_time - created_at).total_seconds() / 3600, 1)

        print(f"[DEBUG] MR created: {created_at}")
        print(f"[DEBUG] First comment: {first_time}")
        print(f"[DEBUG] Delay hours: {delay_hours}")
        print(f"[DEBUG] Comments count: {len(comments)}")
    
        return {
            'total': len(comments),
            'by_type': dict(by_type),
            'by_author': dict(by_author),
            'participants': list(participants),
            'first_comment_delay_hours': delay_hours,
            'reviewers_count': len(participants)
        }

    def _count_iterations(self, commits: List[Dict], created_at: datetime) -> int:
        if not commits:
            return 0
        times = sorted([
            datetime.fromisoformat(c['created_at'].replace('Z', '+00:00'))
            for c in commits
        ])
        iterations = 1
        for i in range(1, len(times)):
            if (times[i] - times[i-1]).total_seconds() / 3600 > 2:
                iterations += 1
        return iterations

    def _calculate_mr_quality_score(self, mr: Dict, commits: List[Dict], 
                                     comments: List[Dict], lines_changed: int = 0,
                                     additions: int = 0, deletions: int = 0) -> Dict:
        description = mr.get('description', '') or ''
        iterations = self._count_iterations(
            commits,
            datetime.fromisoformat(mr['created_at'].replace('Z', '+00:00'))
        )
        comments_count = len(comments)
        size_value = lines_changed if lines_changed > 0 else mr.get('changes_count', 0)
        
        return {
            "signals": {
                "small_size": size_value < 500,
                "has_description": len(description) > 20,
                "minimal_rework": iterations <= 2,
                "has_review_discussion": comments_count > 0,
                "quick_first_review": None  
            },
            "details": {
                "size": size_value,
                "additions": additions, 
                "deletions": deletions,   
                "changes_count": size_value,
                "description_length": len(description),
                "description_preview": (description[:100] + "...") if len(description) > 100 else description,
                "iterations": iterations,
                "comments_count": comments_count,
                "created_at": mr['created_at']
            },
            "quality_ratio": round(sum([
                size_value < 500,
                len(description) > 20,
                iterations <= 2,
                comments_count > 0
            ]) / 4, 2)
        }

    async def generate_full_report(self, days: int = 30) -> Dict:
        """Генерирует отчёт для текущего проекта"""
        if not self.project_id:
            raise ValueError("project_id is required for single project report")
        
        branches = await self.get_all_branches()
        
        seen_commit_ids: Set[str] = set()
        all_commits = []
        
        for branch in branches:
            commits = await self.get_commits_for_branch(
                branch['name'], 
                days=days, 
                seen_ids=seen_commit_ids
            )
            all_commits.extend(commits)
        
        all_mrs = await self.get_merge_requests_detailed(days=days)
        commit_stats = self.get_commit_activity_stats(all_commits)
        print(f"[DEBUG] GitLabAnalyticsComplete: commit_messages keys = {list(commit_stats.get('commit_messages', {}).keys())}")
        
        project_info = await self.get_project_info()
        
        return {
            'project_id': int(self.project_id),
            'period_days': days,
            'generated_at': datetime.now().isoformat(),
            'project_name': project_info.get('name', 'Unknown'),
            'total_branches': len(branches),
            'commits': {
                'total': len(all_commits),
                'by_author': commit_stats.get('authors', {}),
                'total_additions': commit_stats.get('total_additions', 0),
                'total_deletions': commit_stats.get('total_deletions', 0),
                'activity_by_hour': commit_stats.get('commits_by_hour', {}),
                'activity_by_weekday': commit_stats.get('commits_by_weekday', {}),
                'activity_by_date': commit_stats.get('commits_by_date', {}),
                'commit_messages': commit_stats.get('commit_messages', {})
            },
            'merge_requests': {
                'list': all_mrs,
                'stats': self._aggregate_mr_stats(all_mrs)
            },
            'comments': self._aggregate_comments_stats(all_mrs)
        }

    def _aggregate_mr_stats(self, mrs: List[Dict]) -> Dict:
        if not mrs:
            return {
                'total': 0,
                'opened': 0,
                'merged': 0,
                'closed': 0,
                'avg_time_to_merge_hours': None,
                'authors': {}
            }
        
        stats = {
            'total': len(mrs),
            'opened': 0,
            'merged': 0,
            'closed': 0,
            'authors': defaultdict(int),
            'time_to_merge': []
        }
        
        for m in mrs:
            if m['state'] == 'opened':
                stats['opened'] += 1
            elif m['state'] == 'merged':
                stats['merged'] += 1
            elif m['state'] == 'closed':
                stats['closed'] += 1
            
            stats['authors'][m['actual_author']] += 1
            
            if m.get('time_to_merge_hours') is not None:
                stats['time_to_merge'].append(m['time_to_merge_hours'])
        
        return {
            'total': stats['total'],
            'opened': stats['opened'],
            'merged': stats['merged'],
            'closed': stats['closed'],
            'avg_time_to_merge_hours': (
                sum(stats['time_to_merge']) / len(stats['time_to_merge'])
                if stats['time_to_merge'] else None
            ),
            'authors': dict(stats['authors'])
        }

    def _aggregate_comments_stats(self, mrs: List[Dict]) -> Dict:
        total = 0
        by_type = defaultdict(int)
        by_author = defaultdict(int)
        
        for m in mrs:
            for c in m.get('comments', []):
                total += 1
                by_type[c['type']] += 1
                by_author[c['author']] += 1
        
        return {
            'total_comments': total,
            'by_type': dict(by_type),
            'by_author': dict(by_author),
            'per_mr_avg': total / len(mrs) if mrs else 0
        }


class MultiProjectAnalytics:
    """Агрегированная аналитика по нескольким проектам"""
    
    def __init__(self, project_ids: List[int]):
        self.project_ids = project_ids
        self.user_mapper = UserMapper()
    
    async def generate_aggregated_report(self, days: int = 30) -> Dict:
        """Собирает отчёты по всем проектам и агрегирует"""
        
        all_commits_by_author = defaultdict(lambda: {
            'commits': 0, 
            'additions': 0, 
            'deletions': 0, 
            'projects': set(),
            'activity_by_date': defaultdict(int),
            'commit_messages': [] 
        })
        all_commits_by_date = defaultdict(int)
        all_mrs = []
        project_reports = {}
        
        tasks = []
        for pid in self.project_ids:
            analytics = GitLabAnalyticsComplete(project_id=pid)
            tasks.append(self._fetch_project_report(analytics, pid, days))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for pid, result in zip(self.project_ids, results):
            if isinstance(result, Exception):
                print(f"[ERROR] Ошибка для проекта {pid}: {result}")
                continue
            
            project_reports[pid] = {
                'name': result.get('project_name', 'Unknown'),
                'commits_total': result['commits']['total'],
                'mrs_total': len(result['merge_requests']['list']),
            }
            
            for author, stats in result['commits']['by_author'].items():
                normalized = self.user_mapper.normalize_author(author)
                print(f"[DEBUG MULTI] Проект {pid}: автор '{author}' -> '{normalized}'")
                print(f"[DEBUG MULTI]   commits: {stats.get('commits', 0)}")
                print(f"[DEBUG MULTI]   commit_messages count: {len(stats.get('commit_messages', []))}")
                print(f"[DEBUG MULTI]   commit_messages: {stats.get('commit_messages', [])[:2]}")
                
                all_commits_by_author[normalized]['commits'] += stats.get('commits', 0)
                all_commits_by_author[normalized]['additions'] += stats.get('additions', 0)
                all_commits_by_author[normalized]['deletions'] += stats.get('deletions', 0)
                all_commits_by_author[normalized]['projects'].add(pid)

                if 'commit_messages' in stats:
                    all_commits_by_author[normalized]['commit_messages'].extend(stats['commit_messages'])   
                if 'activity_by_date' in stats:
                    for date, count in stats['activity_by_date'].items():
                        all_commits_by_author[normalized]['activity_by_date'][date] += count

            if result['commits'].get('activity_by_date'):
                for date, count in result['commits']['activity_by_date'].items():
                    all_commits_by_date[date] += count

            for mr in result['merge_requests']['list']:
                mr['project_id'] = pid
                mr['project_name'] = result.get('project_name', 'Unknown')
                all_mrs.append(mr)
        
        for author_data in all_commits_by_author.values():
            author_data['projects'] = list(author_data['projects'])
            author_data['activity_by_date'] = dict(author_data['activity_by_date'])
        
        return {
            'mode': 'aggregated',
            'project_ids': self.project_ids,
            'projects': project_reports,
            'period_days': days,
            'generated_at': datetime.now().isoformat(),
            'commits': {
                'total': sum(p['commits_total'] for p in project_reports.values()),
                'by_author': dict(all_commits_by_author),
                'activity_by_date': dict(all_commits_by_date),
                'commit_messages': {
                    author: data['commit_messages'] 
                    for author, data in all_commits_by_author.items()
                }
            },
            'merge_requests': {
                'list': all_mrs,
                'total': len(all_mrs),
            },
        }
    
    async def _fetch_project_report(
        self, analytics: GitLabAnalyticsComplete, project_id: int, days: int
    ) -> Dict:
        return await analytics.generate_full_report(days=days)