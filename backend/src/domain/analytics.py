import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import List, Dict, Set, Optional, Tuple
from dotenv import load_dotenv
import aiohttp

from src.domain.user_mapper import UserMapper
from src.infrastructure.http_session import get_session
from src.infrastructure.cache import cached

load_dotenv()


_GITLAB_SEMAPHORE = asyncio.Semaphore(10)

STALE_THRESHOLD_DAYS = 7

_TEST_PATH_PATTERNS = [
    re.compile(r"(^|/)tests?/", re.IGNORECASE),
    re.compile(r"(^|/)__tests__/", re.IGNORECASE),
    re.compile(r"(^|/)specs?/", re.IGNORECASE),
    re.compile(r"(_test|\.test|_spec|\.spec)\.[a-z0-9]+$", re.IGNORECASE),
    re.compile(r"(^|/)test_[^/]+\.py$", re.IGNORECASE),
]


def _now_ms() -> float:
    return time.perf_counter() * 1000


def _log(stage: str, msg: str) -> None:
    print(f"[{stage}] {msg}", flush=True)


def _size_bucket(total_changes: int) -> str:
    if total_changes < 50:
        return "XS"
    if total_changes < 200:
        return "S"
    if total_changes < 500:
        return "M"
    if total_changes < 1000:
        return "L"
    return "XL"


def _is_test_file(path: str) -> bool:
    if not path:
        return False
    return any(p.search(path) for p in _TEST_PATH_PATTERNS)


def _parse_diff_lines(diff_text: str) -> Tuple[int, int]:
    """Считает +/- строки в unified-диффе (исключая заголовки +++/---/@@)"""
    additions = 0
    deletions = 0
    for line in (diff_text or "").splitlines():
        if not line:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line[0] == "+":
            additions += 1
        elif line[0] == "-":
            deletions += 1
    return additions, deletions


class GitLabAnalyticsComplete:
    """Аналитика для одного проекта GitLab"""

    def __init__(self, project_id: Optional[int] = None):
        self.token = os.getenv("GITLAB_TOKEN", "").strip()
        self.url = os.getenv("GITLAB_URL", "https://gitlab.com").strip()
        self.user_mapper = UserMapper()

        if project_id is not None:
            self.project_id = str(project_id)
        else:
            self.project_id = os.getenv("GITLAB_PROJECT_ID", "").strip() or None

    def _get_auth_headers(self) -> Dict[str, str]:
        return {
            "PRIVATE-TOKEN": self.token,
            "User-Agent": "TeamPerformanceHub/1.0",
            "Content-Type": "application/json",
        }

    async def _gitlab_get(
        self,
        session: aiohttp.ClientSession,
        endpoint: str,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        url = f"{self.url}/api/v4{endpoint}"
        headers = self._get_auth_headers()

        async with _GITLAB_SEMAPHORE:
            try:
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 404:
                        print(f"[WARN] 404: {endpoint}")
                        return None
                    error_text = await response.text()
                    print(f"[ERROR] {response.status} при запросе {endpoint}: {error_text[:200]}")
                    return None
            except Exception as e:
                print(f"[ERROR] Сетевая ошибка при запросе {endpoint}: {type(e).__name__}: {e}")
                return None

    async def _gitlab_get_paginated(
        self,
        session: aiohttp.ClientSession,
        endpoint: str,
        params: Optional[Dict] = None,
    ) -> List[Dict]:
        items: List[Dict] = []
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
                if len(data) < per_page:
                    break
                page += 1
            else:
                items.append(data)
                break

        return items

    async def get_project_info(self) -> Dict:
        if not self.project_id:
            return {"name": "All Projects"}
        session = get_session()
        data = await self._gitlab_get(session, f"/projects/{self.project_id}")
        return data or {}

    async def get_all_branches(self) -> List[Dict]:
        if not self.project_id:
            return []

        session = get_session()
        data = await self._gitlab_get_paginated(
            session, f"/projects/{self.project_id}/repository/branches"
        )

        return [
            {
                "name": branch["name"],
                "commit": branch["commit"]["short_id"],
                "commit_date": branch["commit"].get("created_at"),
                "protected": branch.get("protected", False),
                "default": branch.get("default", False),
            }
            for branch in data
        ]

    async def get_commits_for_branch(
        self, branch_name: str, days: int = 90, seen_ids: Optional[Set[str]] = None
    ) -> List[Dict]:
        """Получает коммиты для ветки со статистикой (?with_stats=true), дедуп через seen_ids"""
        if not self.project_id:
            return []

        if seen_ids is None:
            seen_ids = set()

        session = get_session()
        since_date = (datetime.now() - timedelta(days=days)).isoformat()
        params = {"ref_name": branch_name, "since": since_date, "with_stats": "true"}

        commits_data = await self._gitlab_get_paginated(
            session, f"/projects/{self.project_id}/repository/commits", params
        )

        commits: List[Dict] = []
        for commit in commits_data:
            if commit["id"] in seen_ids:
                continue
            seen_ids.add(commit["id"])

            stats = commit.get("stats") or {}
            commit_date = datetime.fromisoformat(commit["created_at"].replace("Z", "+00:00"))
            commits.append({
                "id": commit["id"],
                "short_id": commit["short_id"],
                "title": commit["title"],
                "message": commit["message"],
                "author_name": self.user_mapper.normalize_author(commit["author_name"]),
                "author_email": commit["author_email"],
                "created_at": commit["created_at"],
                "date": commit_date,
                "hour": commit_date.hour,
                "weekday": commit_date.weekday(),
                "additions": stats.get("additions", 0),
                "deletions": stats.get("deletions", 0),
                "total_changes": stats.get("total", 0),
            })
        return commits

    def get_commit_activity_stats(self, commits: List[Dict]) -> Dict:
        if not commits:
            return {
                "total_commits": 0,
                "total_additions": 0,
                "total_deletions": 0,
                "authors": {},
                "commits_by_hour": {},
                "commits_by_weekday": {},
                "commits_by_date": defaultdict(int),
                "commit_messages": {},
                "first_commit": None,
                "last_commit": None,
            }

        stats = {
            "total_commits": len(commits),
            "total_additions": sum(c["additions"] for c in commits),
            "total_deletions": sum(c["deletions"] for c in commits),
            "authors": defaultdict(lambda: {
                "commits": 0, "additions": 0, "deletions": 0,
                "activity_by_date": defaultdict(int),
            }),
            "commits_by_hour": defaultdict(int),
            "commits_by_weekday": defaultdict(int),
            "commits_by_date": defaultdict(int),
            "commit_messages": defaultdict(list),
            "first_commit": commits[-1]["created_at"] if commits else None,
            "last_commit": commits[0]["created_at"] if commits else None,
        }

        for commit in commits:
            author = commit["author_name"]
            date_str = commit["date"].date().isoformat()
            stats["authors"][author]["commits"] += 1
            stats["authors"][author]["additions"] += commit["additions"]
            stats["authors"][author]["deletions"] += commit["deletions"]
            stats["commit_messages"][author].append(commit.get("message", ""))
            stats["commits_by_hour"][commit["hour"]] += 1
            stats["commits_by_weekday"][commit["weekday"]] += 1
            stats["commits_by_date"][date_str] += 1
            stats["authors"][author]["activity_by_date"][date_str] += 1

        stats["authors"] = {
            k: {
                "commits": v["commits"],
                "additions": v["additions"],
                "deletions": v["deletions"],
                "activity_by_date": dict(v["activity_by_date"]),
                "commit_messages": stats["commit_messages"].get(k, []),
            }
            for k, v in stats["authors"].items()
        }

        stats["commits_by_hour"] = dict(stats["commits_by_hour"])
        stats["commits_by_weekday"] = dict(stats["commits_by_weekday"])
        stats["commits_by_date"] = dict(stats["commits_by_date"])
        stats["commit_messages"] = dict(stats["commit_messages"])

        print(f"[DEBUG] Total commits: {stats['total_commits']}")
        print(f"[DEBUG] Authors: {list(stats['authors'].keys())}")

        return stats

    async def get_merge_request_comments(self, mr_iid: int) -> List[Dict]:
        if not self.project_id:
            return []

        session = get_session()
        endpoint = f"/projects/{self.project_id}/merge_requests/{mr_iid}/discussions"
        discussions = await self._gitlab_get_paginated(session, endpoint)

        comments: List[Dict] = []
        for discussion in discussions:
            for note in discussion.get("notes", []):
                if note.get("system", False):
                    continue
                comment = {
                    "id": note["id"],
                    "author": self.user_mapper.normalize_author(note["author"]["name"]),
                    "author_username": note["author"]["username"],
                    "created_at": note["created_at"],
                    "body": note["body"],
                    "type": self._classify_comment(note["body"]),
                    "is_reply": note.get("type") == "DiscussionNote",
                    "discussion_id": discussion.get("id"),
                }
                if note.get("position"):
                    pos = note["position"]
                    comment["file_path"] = pos.get("new_path") or pos.get("old_path")
                    comment["line"] = pos.get("new_line") or pos.get("old_line")
                comments.append(comment)

        return comments

    def _classify_comment(self, comment_body: str) -> str:
        body_lower = (comment_body or "").lower()
        if any(k in body_lower for k in ["lgtm", "approve", "good", "одобряю", "отлично"]):
            return "approval"
        if any(k in body_lower for k in ["архитектура", "дизайн", "паттерн", "architecture"]):
            return "architectural"
        if any(k in body_lower for k in ["bug", "fix", "error", "issue", "баг", "ошибка"]):
            return "bug"
        if any(k in body_lower for k in ["стиль", "опечатка", "пробел", "nit"]):
            return "nitpick"
        if any(k in body_lower for k in ["предлагаю", "может", "стоит", "лучше", "suggest"]):
            return "suggestion"
        if any(k in body_lower for k in ["?", "почему", "зачем", "как", "что", "question"]):
            return "question"
        return "other"

    async def _get_mr_commits(self, mr_iid: int) -> List[Dict]:
        if not self.project_id:
            return []

        session = get_session()
        endpoint = f"/projects/{self.project_id}/merge_requests/{mr_iid}/commits"
        commits_data = await self._gitlab_get_paginated(session, endpoint)

        return [
            {
                "id": commit["id"],
                "created_at": commit["created_at"],
                "title": commit["title"],
                "author_name": commit.get("author_name", ""),
                "author_email": commit.get("author_email", ""),
            }
            for commit in commits_data
        ]

    async def _fetch_mr_diff_info(self, mr_iid: int) -> Dict:
        """Один запрос /changes даёт: пути изменённых файлов + реальный размер диффа MR"""
        if not self.project_id:
            return {"paths": [], "additions": 0, "deletions": 0}
        session = get_session()
        data = await self._gitlab_get(
            session, f"/projects/{self.project_id}/merge_requests/{mr_iid}/changes"
        )
        if not data:
            return {"paths": [], "additions": 0, "deletions": 0}

        paths: List[str] = []
        total_additions = 0
        total_deletions = 0
        for change in data.get("changes") or []:
            new_path = change.get("new_path") or change.get("old_path")
            if new_path:
                paths.append(new_path)
            add, dele = _parse_diff_lines(change.get("diff") or "")
            total_additions += add
            total_deletions += dele

        return {"paths": paths, "additions": total_additions, "deletions": total_deletions}

    async def _process_mr(
        self,
        mr: Dict,
        state: str,
    ) -> Dict:
        """Обработка одного MR: комменты, коммиты, дифф — параллельно.
        Размер MR считается из реального диффа MR (не из суммы коммитов)."""
        created_at = datetime.fromisoformat(mr["created_at"].replace("Z", "+00:00"))

        comments, commits, diff_info = await asyncio.gather(
            self.get_merge_request_comments(mr["iid"]),
            self._get_mr_commits(mr["iid"]),
            self._fetch_mr_diff_info(mr["iid"]),
        )
        changed_paths = diff_info["paths"]
        total_additions = diff_info["additions"]
        total_deletions = diff_info["deletions"]

        comment_stats = self._calculate_comment_stats(comments, created_at)

        commit_authors = set(c["author_name"] for c in commits if c.get("author_name"))
        if commit_authors:
            real_author = next(iter(commit_authors))
            real_author = self.user_mapper.normalize_author(real_author)
            real_author_username = None
            for commit in commits:
                if self.user_mapper.normalize_author(commit.get("author_name", "")) == real_author:
                    email = commit.get("author_email", "")
                    if email:
                        real_author_username = email.split("@")[0]
                    break
            if not real_author_username:
                real_author_username = real_author.lower().replace(" ", ".")
        else:
            real_author = self.user_mapper.normalize_author(mr["author"]["name"])
            real_author_username = mr["author"]["username"]

        merged_by = None
        merged_by_username = None
        if mr.get("merged_by"):
            merged_by = mr["merged_by"].get("name")
            merged_by_username = mr["merged_by"].get("username")
        elif mr.get("merge_user"):
            merged_by = mr["merge_user"].get("name")
            merged_by_username = mr["merge_user"].get("username")

        total_changes = total_additions + total_deletions
        mr_quality = self._calculate_mr_quality_score(
            mr, commits, comments, total_changes, total_additions, total_deletions
        )

        test_paths = [p for p in changed_paths if _is_test_file(p)]
        size_bucket = _size_bucket(total_changes)

        is_stale = False
        if state == "opened" and mr.get("updated_at"):
            updated_at = datetime.fromisoformat(mr["updated_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            is_stale = (now - updated_at).days >= STALE_THRESHOLD_DAYS

        mr_data = {
            "iid": mr["iid"],
            "title": mr["title"],
            "description": mr.get("description", ""),
            "author": self.user_mapper.normalize_author(mr["author"]["name"]),
            "author_username": mr["author"]["username"],
            "actual_author": real_author,
            "actual_author_username": real_author_username,
            "merged_by": merged_by,
            "merged_by_username": merged_by_username,
            "created_at": mr["created_at"],
            "updated_at": mr.get("updated_at"),
            "merged_at": mr.get("merged_at"),
            "state": state,
            "source_branch": mr["source_branch"],
            "target_branch": mr["target_branch"],
            "web_url": mr["web_url"],
            "changes_count": mr.get("changes_count", 0),
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "total_changes": total_changes,
            "commits_count": len(commits),
            "comments": comments,
            "comment_stats": comment_stats,
            "quality_score": mr_quality,
            "iterations": self._count_iterations(commits, created_at),
            "total_lines_changed": total_changes,
            "additions": total_additions,
            "deletions": total_deletions,
            "size_bucket": size_bucket,
            "is_stale": is_stale,
            "changed_files_count": len(changed_paths),
            "test_files_count": len(test_paths),
            "has_tests": len(test_paths) > 0,
        }

        if state == "merged" and mr.get("merged_at"):
            merged_at = datetime.fromisoformat(mr["merged_at"].replace("Z", "+00:00"))
            mr_data["time_to_merge_hours"] = (merged_at - created_at).total_seconds() / 3600
        else:
            mr_data["time_to_merge_hours"] = None

        return mr_data

    async def get_merge_requests_detailed(self, days: int = 90) -> List[Dict]:
        if not self.project_id:
            return []

        session = get_session()
        since_date = (datetime.now() - timedelta(days=days)).isoformat()

        progress = {"done": 0, "total": 0}

        async def fetch_state(state: str) -> List[Dict]:
            t = _now_ms()
            params = {
                "state": state,
                "updated_after": since_date,
                "order_by": "updated_at",
                "sort": "desc",
            }
            mrs = await self._gitlab_get_paginated(
                session, f"/projects/{self.project_id}/merge_requests", params
            )
            _log("mr", f"project={self.project_id} state={state}: получен список ({len(mrs)} шт.) за {int(_now_ms() - t)}мс")
            if not mrs:
                return []
            progress["total"] += len(mrs)

            async def process(mr):
                tt = _now_ms()
                result = await self._process_mr(mr, state)
                progress["done"] += 1
                _log(
                    "mr",
                    f"project={self.project_id} [{progress['done']}/{progress['total']}] "
                    f"{state} iid={mr['iid']} size={result.get('total_changes', 0)}строк "
                    f"за {int(_now_ms() - tt)}мс",
                )
                return result

            return await asyncio.gather(*(process(mr) for mr in mrs))

        state_results = await asyncio.gather(*(
            fetch_state(s) for s in ["opened", "merged", "closed"]
        ))
        return [mr for group in state_results for mr in group]

    def _calculate_comment_stats(self, comments: List[Dict], created_at: datetime) -> Dict:
        if not comments:
            return {
                "total": 0,
                "by_type": {},
                "by_author": {},
                "participants": [],
                "first_comment_delay_hours": None,
                "reviewers_count": 0,
            }

        by_type = defaultdict(int)
        by_author = defaultdict(int)
        participants = set()

        for c in comments:
            by_type[c["type"]] += 1
            by_author[c["author"]] += 1
            participants.add(c["author"])

        first_comment = min(comments, key=lambda x: x["created_at"])
        first_time = datetime.fromisoformat(first_comment["created_at"].replace("Z", "+00:00"))
        delay_hours = round((first_time - created_at).total_seconds() / 3600, 1)

        return {
            "total": len(comments),
            "by_type": dict(by_type),
            "by_author": dict(by_author),
            "participants": list(participants),
            "first_comment_delay_hours": delay_hours,
            "reviewers_count": len(participants),
        }

    def _count_iterations(self, commits: List[Dict], created_at: datetime) -> int:
        if not commits:
            return 0
        times = sorted([
            datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
            for c in commits
        ])
        iterations = 1
        for i in range(1, len(times)):
            if (times[i] - times[i - 1]).total_seconds() / 3600 > 2:
                iterations += 1
        return iterations

    def _calculate_mr_quality_score(
        self,
        mr: Dict,
        commits: List[Dict],
        comments: List[Dict],
        lines_changed: int = 0,
        additions: int = 0,
        deletions: int = 0,
    ) -> Dict:
        description = mr.get("description", "") or ""
        iterations = self._count_iterations(
            commits,
            datetime.fromisoformat(mr["created_at"].replace("Z", "+00:00")),
        )
        comments_count = len(comments)
        size_value = lines_changed if lines_changed > 0 else mr.get("changes_count", 0)

        return {
            "signals": {
                "small_size": size_value < 500,
                "has_description": len(description) > 20,
                "minimal_rework": iterations <= 2,
                "has_review_discussion": comments_count > 0,
                "quick_first_review": None,
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
                "created_at": mr["created_at"],
            },
            "quality_ratio": round(sum([
                size_value < 500,
                len(description) > 20,
                iterations <= 2,
                comments_count > 0,
            ]) / 4, 2),
        }

    async def generate_full_report(self, days: int = 30) -> Dict:
        if not self.project_id:
            raise ValueError("project_id is required for single project report")
        return await self._generate_full_report_cached(self.project_id, days)

    @cached(ttl=300, key_prefix="analytics.full_report")
    async def _generate_full_report_cached(self, project_id: str, days: int) -> Dict:
        """Отчёт по одному проекту: ветки и MR — параллельно. TTL-кэш 5 мин на (project_id, days)"""
        t_total = _now_ms()
        _log("report", f"project={self.project_id} days={days} — старт")

        t = _now_ms()
        branches = await self.get_all_branches()
        _log("report", f"project={self.project_id} ветки: {len(branches)} шт. за {int(_now_ms() - t)}мс")

        seen_commit_ids: Set[str] = set()

        t = _now_ms()
        _log("report", f"project={self.project_id} загрузка коммитов по {len(branches)} веткам (параллельно)...")
        branch_results = await asyncio.gather(*(
            self.get_commits_for_branch(b["name"], days=days, seen_ids=seen_commit_ids)
            for b in branches
        ))
        all_commits: List[Dict] = [c for commits in branch_results for c in commits]
        _log("report", f"project={self.project_id} коммитов всего: {len(all_commits)} за {int(_now_ms() - t)}мс")

        t = _now_ms()
        _log("report", f"project={self.project_id} загрузка MR (3 состояния параллельно)...")
        all_mrs_task = self.get_merge_requests_detailed(days=days)
        project_info_task = self.get_project_info()
        all_mrs, project_info = await asyncio.gather(all_mrs_task, project_info_task)
        _log("report", f"project={self.project_id} MR: {len(all_mrs)} шт. за {int(_now_ms() - t)}мс")

        commit_stats = self.get_commit_activity_stats(all_commits)
        _log("report", f"project={self.project_id} ГОТОВО за {int(_now_ms() - t_total)}мс")

        return {
            "project_id": int(self.project_id),
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "project_name": project_info.get("name", "Unknown"),
            "total_branches": len(branches),
            "commits": {
                "total": len(all_commits),
                "by_author": commit_stats.get("authors", {}),
                "total_additions": commit_stats.get("total_additions", 0),
                "total_deletions": commit_stats.get("total_deletions", 0),
                "activity_by_hour": commit_stats.get("commits_by_hour", {}),
                "activity_by_weekday": commit_stats.get("commits_by_weekday", {}),
                "activity_by_date": commit_stats.get("commits_by_date", {}),
                "commit_messages": commit_stats.get("commit_messages", {}),
            },
            "merge_requests": {
                "list": all_mrs,
                "stats": self._aggregate_mr_stats(all_mrs),
            },
            "comments": self._aggregate_comments_stats(all_mrs),
            "review_activity": self._aggregate_review_activity(all_mrs),
            "size_distribution": self._aggregate_size_distribution(all_mrs),
            "tests_ratio": self._aggregate_tests_ratio(all_mrs),
            "wip_stale": self._aggregate_wip_stale(all_mrs),
        }

    def _aggregate_mr_stats(self, mrs: List[Dict]) -> Dict:
        if not mrs:
            return {
                "total": 0,
                "opened": 0,
                "merged": 0,
                "closed": 0,
                "avg_time_to_merge_hours": None,
                "authors": {},
            }

        stats = {
            "total": len(mrs),
            "opened": 0,
            "merged": 0,
            "closed": 0,
            "authors": defaultdict(int),
            "time_to_merge": [],
        }

        for m in mrs:
            if m["state"] == "opened":
                stats["opened"] += 1
            elif m["state"] == "merged":
                stats["merged"] += 1
            elif m["state"] == "closed":
                stats["closed"] += 1

            stats["authors"][m["actual_author"]] += 1

            if m.get("time_to_merge_hours") is not None:
                stats["time_to_merge"].append(m["time_to_merge_hours"])

        return {
            "total": stats["total"],
            "opened": stats["opened"],
            "merged": stats["merged"],
            "closed": stats["closed"],
            "avg_time_to_merge_hours": (
                sum(stats["time_to_merge"]) / len(stats["time_to_merge"])
                if stats["time_to_merge"] else None
            ),
            "authors": dict(stats["authors"]),
        }

    def _aggregate_comments_stats(self, mrs: List[Dict]) -> Dict:
        total = 0
        by_type = defaultdict(int)
        by_author = defaultdict(int)

        for m in mrs:
            for c in m.get("comments", []):
                total += 1
                by_type[c["type"]] += 1
                by_author[c["author"]] += 1

        return {
            "total_comments": total,
            "by_type": dict(by_type),
            "by_author": dict(by_author),
            "per_mr_avg": total / len(mrs) if mrs else 0,
        }

    def _aggregate_review_activity(self, mrs: List[Dict]) -> Dict:
        """
        Собирает:
        - graph: {reviewer: {author: count}} — кто чьи MR ревьюит (исключая самокомменты)
        - given_by: {reviewer: total} — сколько коментов дано
        - received_by: {author: total} — сколько коментов получено
        """
        graph: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        given_by: Dict[str, int] = defaultdict(int)
        received_by: Dict[str, int] = defaultdict(int)

        for mr in mrs:
            mr_author = mr.get("actual_author") or mr.get("author") or ""
            for c in mr.get("comments", []):
                reviewer = c.get("author") or ""
                if not reviewer or not mr_author:
                    continue
                if reviewer == mr_author:
                    continue  # самокомменты не считаем
                graph[reviewer][mr_author] += 1
                given_by[reviewer] += 1
                received_by[mr_author] += 1

        return {
            "graph": {r: dict(authors) for r, authors in graph.items()},
            "given_by": dict(given_by),
            "received_by": dict(received_by),
        }

    def _aggregate_size_distribution(self, mrs: List[Dict]) -> Dict[str, int]:
        """Распределение MR по размеру: {XS: N, S: N, ...}"""
        buckets: Dict[str, int] = {"XS": 0, "S": 0, "M": 0, "L": 0, "XL": 0}
        for mr in mrs:
            b = mr.get("size_bucket") or _size_bucket(mr.get("total_changes", 0))
            buckets[b] = buckets.get(b, 0) + 1
        return buckets

    def _aggregate_tests_ratio(self, mrs: List[Dict]) -> Dict:
        """Доля MR с тестами"""
        total = len(mrs)
        with_tests = sum(1 for mr in mrs if mr.get("has_tests"))
        return {
            "total_mrs": total,
            "mrs_with_tests": with_tests,
            "ratio": (with_tests / total) if total else 0.0,
        }

    def _aggregate_wip_stale(self, mrs: List[Dict]) -> Dict:
        """WIP = открытые MR; stale = WIP, updated_at > STALE_THRESHOLD_DAYS назад"""
        wip_by_author: Dict[str, int] = defaultdict(int)
        stale_by_author: Dict[str, int] = defaultdict(int)
        for mr in mrs:
            if mr.get("state") != "opened":
                continue
            author = mr.get("actual_author") or mr.get("author") or ""
            if not author:
                continue
            wip_by_author[author] += 1
            if mr.get("is_stale"):
                stale_by_author[author] += 1
        return {
            "wip_by_author": dict(wip_by_author),
            "stale_by_author": dict(stale_by_author),
            "stale_threshold_days": STALE_THRESHOLD_DAYS,
        }


class MultiProjectAnalytics:
    """Агрегированная аналитика по нескольким проектам"""

    def __init__(self, project_ids: List[int]):
        self.project_ids = project_ids
        self.user_mapper = UserMapper()

    async def generate_aggregated_report(self, days: int = 30) -> Dict:
        return await self._generate_aggregated_report_cached(tuple(self.project_ids), days)

    @cached(ttl=300, key_prefix="analytics.aggregated_report")
    async def _generate_aggregated_report_cached(self, project_ids_key: tuple, days: int) -> Dict:
        """Собирает отчёты по всем проектам параллельно и агрегирует. TTL-кэш 5 мин"""

        all_commits_by_author = defaultdict(lambda: {
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "projects": set(),
            "activity_by_date": defaultdict(int),
            "commit_messages": [],
        })
        all_commits_by_date = defaultdict(int)
        all_mrs: List[Dict] = []
        project_reports: Dict[int, Dict] = {}

        tasks = [
            self._fetch_project_report(GitLabAnalyticsComplete(project_id=pid), pid, days)
            for pid in self.project_ids
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for pid, result in zip(self.project_ids, results):
            if isinstance(result, Exception):
                print(f"[ERROR] Ошибка для проекта {pid}: {result}")
                continue

            project_reports[pid] = {
                "name": result.get("project_name", "Unknown"),
                "commits_total": result["commits"]["total"],
                "mrs_total": len(result["merge_requests"]["list"]),
            }

            for author, stats in result["commits"]["by_author"].items():
                normalized = self.user_mapper.normalize_author(author)
                all_commits_by_author[normalized]["commits"] += stats.get("commits", 0)
                all_commits_by_author[normalized]["additions"] += stats.get("additions", 0)
                all_commits_by_author[normalized]["deletions"] += stats.get("deletions", 0)
                all_commits_by_author[normalized]["projects"].add(pid)

                if "commit_messages" in stats:
                    all_commits_by_author[normalized]["commit_messages"].extend(stats["commit_messages"])
                if "activity_by_date" in stats:
                    for date, count in stats["activity_by_date"].items():
                        all_commits_by_author[normalized]["activity_by_date"][date] += count

            if result["commits"].get("activity_by_date"):
                for date, count in result["commits"]["activity_by_date"].items():
                    all_commits_by_date[date] += count

            for mr in result["merge_requests"]["list"]:
                mr["project_id"] = pid
                mr["project_name"] = result.get("project_name", "Unknown")
                all_mrs.append(mr)

        for author_data in all_commits_by_author.values():
            author_data["projects"] = list(author_data["projects"])
            author_data["activity_by_date"] = dict(author_data["activity_by_date"])

        # Переиспользуем агрегаторы одного-проектного класса
        aggregator = GitLabAnalyticsComplete(project_id=None)
        aggregator.project_id = "0"  # чтобы методы не падали; они читают только mrs

        return {
            "mode": "aggregated",
            "project_ids": self.project_ids,
            "projects": project_reports,
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "commits": {
                "total": sum(p["commits_total"] for p in project_reports.values()),
                "by_author": dict(all_commits_by_author),
                "activity_by_date": dict(all_commits_by_date),
                "commit_messages": {
                    author: data["commit_messages"]
                    for author, data in all_commits_by_author.items()
                },
            },
            "merge_requests": {
                "list": all_mrs,
                "total": len(all_mrs),
            },
            "review_activity": aggregator._aggregate_review_activity(all_mrs),
            "size_distribution": aggregator._aggregate_size_distribution(all_mrs),
            "tests_ratio": aggregator._aggregate_tests_ratio(all_mrs),
            "wip_stale": aggregator._aggregate_wip_stale(all_mrs),
        }

    async def _fetch_project_report(
        self, analytics: GitLabAnalyticsComplete, project_id: int, days: int
    ) -> Dict:
        return await analytics.generate_full_report(days=days)
