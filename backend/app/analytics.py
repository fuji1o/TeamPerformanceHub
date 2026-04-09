import asyncio
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Set
from dotenv import load_dotenv
import aiohttp
from gidgetlab.aiohttp import GitLabAPI

load_dotenv()


class GitLabAnalyticsComplete:
    def __init__(self):
        self.token = os.getenv("GITLAB_TOKEN", "").strip()
        self.project_id = os.getenv("GITLAB_PROJECT_ID", "").strip()
        self.url = os.getenv("GITLAB_URL", "https://gitlab.com").strip()

    async def get_project_info(self) -> Dict:
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(session, self.token, url=self.url)
            try:
                return await gl.getitem(f"/projects/{self.project_id}")
            except Exception as e:
                print(f"[ERROR] Ошибка получения информации о проекте: {e}")
                return {}

    async def get_all_branches(self) -> List[Dict]:
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(session, self.token, url=self.url)
            branches = []
            try:
                async for branch in gl.getiter(f"/projects/{self.project_id}/repository/branches"):
                    branches.append({
                        'name': branch['name'],
                        'commit': branch['commit']['short_id'],
                        'commit_date': branch['commit']['created_at'],
                        'protected': branch.get('protected', False),
                        'default': branch.get('default', False)
                    })
            except Exception as e:
                print(f"[ERROR] Ошибка получения веток: {e}")
            return branches

    async def get_commits_for_branch(self, branch_name: str, days: int = 90, seen_ids: Set[str] = None) -> List[Dict]:
        """Получает коммиты для ветки, исключая уже обработанные"""
        if seen_ids is None:
            seen_ids = set()
            
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(session, self.token, url=self.url)
            since_date = (datetime.now() - timedelta(days=days)).isoformat()
            params = {"ref_name": branch_name, "since": since_date, "per_page": 100}
            commits = []
            try:
                async for commit in gl.getiter(f"/projects/{self.project_id}/repository/commits", params=params):
                    if commit['id'] in seen_ids:
                        continue
                    seen_ids.add(commit['id'])
                    
                    try:
                        detail = await gl.getitem(f"/projects/{self.project_id}/repository/commits/{commit['id']}")
                        commit_date = datetime.fromisoformat(commit['created_at'].replace('Z', '+00:00'))
                        commits.append({
                            'id': commit['id'],
                            'short_id': commit['short_id'],
                            'title': commit['title'],
                            'message': commit['message'],
                            'author_name': commit['author_name'],
                            'author_email': commit['author_email'],
                            'created_at': commit['created_at'],
                            'date': commit_date,
                            'hour': commit_date.hour,
                            'weekday': commit_date.weekday(),
                            'additions': detail.get('stats', {}).get('additions', 0),
                            'deletions': detail.get('stats', {}).get('deletions', 0),
                            'total_changes': detail.get('stats', {}).get('total', 0)
                        })
                    except Exception as e:
                        print(f"   [WARN] Не удалось получить статистику для {commit['short_id']}: {e}")
            except Exception as e:
                print(f"   [ERROR] Ошибка получения коммитов для ветки {branch_name}: {e}")
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
                'commits_by_date': {},
                'first_commit': None,
                'last_commit': None
            }
        
        stats = {
            'total_commits': len(commits),
            'total_additions': sum(c['additions'] for c in commits),
            'total_deletions': sum(c['deletions'] for c in commits),
            'authors': defaultdict(lambda: {'commits': 0, 'additions': 0, 'deletions': 0}),
            'commits_by_hour': defaultdict(int),
            'commits_by_weekday': defaultdict(int),
            'commits_by_date': defaultdict(int),
            'first_commit': commits[-1]['created_at'] if commits else None,
            'last_commit': commits[0]['created_at'] if commits else None
        }
        
        for commit in commits:
            author = commit['author_name']
            stats['authors'][author]['commits'] += 1
            stats['authors'][author]['additions'] += commit['additions']
            stats['authors'][author]['deletions'] += commit['deletions']
            stats['commits_by_hour'][commit['hour']] += 1
            stats['commits_by_weekday'][commit['weekday']] += 1
            stats['commits_by_date'][commit['date'].date().isoformat()] += 1
        
        stats['authors'] = {k: dict(v) for k, v in stats['authors'].items()}
        stats['commits_by_hour'] = dict(stats['commits_by_hour'])
        stats['commits_by_weekday'] = dict(stats['commits_by_weekday'])
        stats['commits_by_date'] = dict(stats['commits_by_date'])
        
        return stats

    async def get_merge_request_comments(self, mr_iid: int) -> List[Dict]:
        comments = []
        url = f"{self.url}/api/v4/projects/{self.project_id}/merge_requests/{mr_iid}/discussions"
        headers = {"Authorization": f"Bearer {self.token}", "User-Agent": "TeamPerformanceHub/1.0"}
        
        try:
            async with aiohttp.ClientSession() as session:
                page = 1
                while True:
                    params = {"per_page": 100, "page": page}
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status != 200:
                            print(f"   [WARN] Ошибка {response.status} при получении комментариев MR !{mr_iid}")
                            break
                        discussions = await response.json()
                        if not discussions:
                            break
                        for discussion in discussions:
                            for note in discussion.get('notes', []):
                                if note.get('system', False):
                                    continue
                                comment = {
                                    'id': note['id'],
                                    'author': note['author']['name'],
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
                    link_header = response.headers.get('Link', '')
                    if 'rel="next"' not in link_header:
                        break
                    page += 1
        except Exception as e:
            print(f"   [ERROR] Сетевая ошибка при получении комментариев MR !{mr_iid}: {e}")
        return comments

    def _classify_comment(self, comment_body: str) -> str:
        body_lower = comment_body.lower()
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

    async def _get_mr_commits(self, gl, mr_iid: int) -> List[Dict]:
        """Получает коммиты MR с информацией об авторах"""
        commits = []
        try:
            async for commit in gl.getiter(f"/projects/{self.project_id}/merge_requests/{mr_iid}/commits"):
                commits.append({
                    'id': commit['id'],
                    'created_at': commit['created_at'],
                    'title': commit['title'],
                    'author_name': commit.get('author_name', ''),
                    'author_email': commit.get('author_email', '')
                })
        except Exception as e:
            print(f"   [WARN] Ошибка получения коммитов MR !{mr_iid}: {e}")
        return commits

    async def get_merge_requests_detailed(self, days: int = 90) -> List[Dict]:
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(session, self.token, url=self.url)
            since_date = (datetime.now() - timedelta(days=days)).isoformat()
            merge_requests = []
            
            for state in ['opened', 'merged', 'closed']:
                params = {
                    "state": state,
                    "per_page": 100,
                    "created_after": since_date,
                    "order_by": "updated_at",
                    "sort": "desc"
                }
                try:
                    async for mr in gl.getiter(f"/projects/{self.project_id}/merge_requests", params=params):
                        created_at = datetime.fromisoformat(mr['created_at'].replace('Z', '+00:00'))
                        comments = await self.get_merge_request_comments(mr['iid'])
                        commits = await self._get_mr_commits(gl, mr['iid'])
                        comment_stats = self._calculate_comment_stats(comments, created_at)

                        total_additions, total_deletions = 0, 0
                        for c in commits:
                            try:
                                c_detail = await gl.getitem(f"/projects/{self.project_id}/repository/commits/{c['id']}")
                                s = c_detail.get('stats', {})
                                total_additions += s.get('additions', 0)
                                total_deletions += s.get('deletions', 0)
                            except Exception:
                                pass

                       
                        commit_authors = set()
                        for commit in commits:
                            if commit.get('author_name'):
                                commit_authors.add(commit['author_name'])
                        
                        #  кто делал коммиты
                        if commit_authors:
                            real_author = next(iter(commit_authors))
                            real_author_username = None
                            for commit in commits:
                                if commit.get('author_name') == real_author:
                                    email = commit.get('author_email', '')
                                    if email:
                                        real_author_username = email.split('@')[0]
                                    break
                            if not real_author_username:
                                real_author_username = real_author.lower().replace(' ', '.')
                        else:
                            # Если нет коммитов, используем автора MR
                            real_author = mr['author']['name']
                            real_author_username = mr['author']['username']
                        
                        # Информация о том, кто смержил
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
                            # API автор (кто создал MR)
                            'author': mr['author']['name'],
                            'author_username': mr['author']['username'],
                            'actual_author': real_author,
                            'actual_author_username': real_author_username,
                            # Кто смержил
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
                        print(f"[DEBUG] MR !{mr['iid']}: API author={mr['author']['name']}, "
                              f"Real author={real_author}, Commits={len(commits)}")
                              
                except Exception as e:
                    print(f"[ERROR] Ошибка получения MR со статусом {state}: {e}")
            
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
        
        return {
            'total': len(comments),
            'by_type': dict(by_type),
            'by_author': dict(by_author),
            'participants': list(participants),
            'first_comment_delay_hours': round((first_time - created_at).total_seconds() / 3600, 1),
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
                "size": lines_changed if lines_changed > 0 else mr.get('changes_count', 0),
                "additions": additions, 
                "deletions": deletions,   
                "changes_count": lines_changed if lines_changed > 0 else mr.get('changes_count', 0),
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
        branches = await self.get_all_branches()
        
        # Используем set для дедупликации коммитов
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
        
        return {
            'period_days': days,
            'generated_at': datetime.now().isoformat(),
            'project_name': (await self.get_project_info()).get('name', 'Unknown'),
            'total_branches': len(branches),
            'commits': {
                'total': len(all_commits),
                'by_author': commit_stats.get('authors', {}),
                'total_additions': commit_stats.get('total_additions', 0),
                'total_deletions': commit_stats.get('total_deletions', 0),
                'activity_by_hour': commit_stats.get('commits_by_hour', {}),
                'activity_by_weekday': commit_stats.get('commits_by_weekday', {})
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
            
            # Используем actual_author для статистики
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


if __name__ == "__main__":
    asyncio.run(GitLabAnalyticsComplete().generate_full_report(30))