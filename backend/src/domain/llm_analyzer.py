import asyncio
import os
import re
import sys
import time
from collections import defaultdict
from typing import List, Optional

import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv

from src.domain.user_mapper import UserMapper

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.domain.analytics import GitLabAnalyticsComplete

load_dotenv()


_LLM_SEMAPHORE = asyncio.Semaphore(10)
_client: Optional[AsyncOpenAI] = None

_CC_TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
_CC_REGEX = re.compile(
    r"^(?P<type>" + "|".join(_CC_TYPES) + r")"
    r"(?:\([^)]+\))?!?:\s+\S.+",
    re.IGNORECASE,
)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not api_key:
            print("ОШИБКА: DEEPSEEK_API_KEY не найден")
            sys.exit(1)
        _client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.AsyncClient(verify=False),
        )
    return _client


def check_conventional_commit(message: str) -> dict:
    """Regex-проверка Conventional Commits — мгновенная, без LLM"""
    first_line = (message or "").strip().split("\n", 1)[0]
    m = _CC_REGEX.match(first_line)
    if m:
        return {"is_conventional": True, "type": m.group("type").lower(), "issue": None}
    return {"is_conventional": False, "type": None, "issue": "Не соответствует формату Conventional Commits"}


class SimpleAnalyzer:
    def __init__(self):
        self.client = _get_client()
        self.model = "deepseek-chat"

    def check_conventional_commit(self, commit_message: str) -> dict:
        return check_conventional_commit(commit_message)

    async def generate_quality_summary(
        self,
        author: str,
        commit_messages: List[str],
        conventional_ratio: int,
        conventional_count: int,
    ) -> str:
        """LLM-оценка качества коммитов: смысловая, а не только формат"""
        total = len(commit_messages)
        if total == 0:
            return f"У разработчика {author} нет коммитов за выбранный период."

        # Короткие уникальные заголовки — даём LLM выборку для оценки содержательности
        seen = set()
        samples: List[str] = []
        for msg in commit_messages:
            first = (msg or "").strip().split("\n", 1)[0][:160]
            if first and first not in seen:
                seen.add(first)
                samples.append(first)
            if len(samples) >= 25:
                break

        samples_block = "\n".join(f"- {s}" for s in samples)

        user_prompt = (
            f"Разработчик: {author}\n"
            f"Всего коммитов: {total}\n"
            f"Соответствует Conventional Commits: {conventional_count}/{total} ({conventional_ratio}%)\n"
            f"Выборка заголовков коммитов (до 25 уникальных):\n"
            f"{samples_block}\n\n"
            "Оцени качество коммитов: информативность сообщений, "
            "соблюдение формата, наличие «мусорных» коммитов (wip, fix, update без деталей). "
            "Дай короткий вердикт для аудитора: 2-3 предложения, без приветствий и подписей."
        )

        print(f"[llm] summary: author={author} commits={total} samples={len(samples)} — старт", flush=True)
        t = time.perf_counter()
        async with _LLM_SEMAPHORE:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Ты аудитор качества коммитов. Отвечай кратко, по делу, на русском.",
                        },
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.4,
                    max_tokens=200,
                )
                elapsed_ms = int((time.perf_counter() - t) * 1000)
                print(f"[llm] summary: author={author} — готово за {elapsed_ms}мс", flush=True)
                return response.choices[0].message.content.strip()
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - t) * 1000)
                print(f"[llm] summary: author={author} — ОШИБКА за {elapsed_ms}мс: {e}", flush=True)
                return (
                    f"Разработчик {author}: {conventional_count} из {total} "
                    f"коммитов соответствуют Conventional Commits ({conventional_ratio}%)."
                )


async def analyze():
    print("АНАЛИЗ КОММИТОВ ПРОЕКТА hub-test")
    print("")

    print("Загрузка данных из GitLab...")
    analytics = GitLabAnalyticsComplete()
    await analytics.generate_full_report(days=90)
    user_mapper = UserMapper()

    all_commits = []
    seen_ids = set()
    for branch in await analytics.get_all_branches():
        commits = await analytics.get_commits_for_branch(branch["name"], days=90, seen_ids=seen_ids)
        for commit in commits:
            all_commits.append({
                "author": commit.get("author_name", "unknown"),
                "message": commit.get("title", "") or commit.get("message", ""),
            })

    print(f"Всего коммитов: {len(all_commits)}")
    print("")

    commits_by_author = defaultdict(list)
    for commit in all_commits:
        normalized_author = user_mapper.normalize_author(commit["author"])
        commits_by_author[normalized_author].append(commit)

    analyzer = SimpleAnalyzer()
    results = []

    for author, commits in commits_by_author.items():
        print("=" * 50)
        print(f"Автор: {author}")
        print(f"Коммитов: {len(commits)}")
        print("")

        conventional_count = 0
        for commit in commits:
            msg = commit["message"]
            result = check_conventional_commit(msg)
            print(f"  Коммит: {msg[:60]}")
            if result["is_conventional"]:
                conventional_count += 1
                print(f"    -> OK (тип: {result['type']})")
            else:
                print("    -> НЕТ: Не соответствует стандарту")

        ratio = int(conventional_count / len(commits) * 100) if commits else 0
        print("")
        print(f"  Conventional Commits: {conventional_count}/{len(commits)} ({ratio}%)")
        print("")
        print("  Summary:")
        wish = await analyzer.generate_quality_summary(
            author=author,
            commit_messages=[c["message"] for c in commits],
            conventional_ratio=ratio,
            conventional_count=conventional_count,
        )
        print(f"    {wish}")
        print("")

        results.append({
            "author": author,
            "commits": len(commits),
            "conventional": conventional_count,
            "ratio": ratio,
            "wish": wish,
        })

    print("=" * 50)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 50)
    print("")

    for res in results:
        if res["ratio"] >= 70:
            status = "ХОРОШО"
        elif res["ratio"] >= 40:
            status = "УЛУЧШИТЬ"
        else:
            status = "ПЛОХО"
        print(f"{res['author']}: {res['ratio']}% соответствия ({status})")

    print("")
    print("Анализ завершен")


if __name__ == "__main__":
    asyncio.run(analyze())
