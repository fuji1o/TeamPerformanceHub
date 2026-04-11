import asyncio
import sys
import os
import json
import re
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv
from src.domain.user_mapper import UserMapper

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.domain.analytics import GitLabAnalyticsComplete

load_dotenv()


class SimpleAnalyzer:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        
        if not api_key:
            print("ОШИБКА: DEEPSEEK_API_KEY не найден")
            sys.exit(1)
        
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = "deepseek-chat"
    
    def check_conventional_commit(self, commit_message: str) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Проверь соответствие Conventional Commits. Ответь JSON: {\"is_conventional\": true/false, \"type\": \"feat|fix|docs|etc\", \"issue\": \"проблема если есть\"}"
                    },
                    {
                        "role": "user",
                        "content": commit_message[:300]
                    }
                ],
                temperature=0.1,
                max_tokens=150
            )
            
            content = response.choices[0].message.content.strip()
            json_match = re.search(r'\{[^{}]*\}', content)
            if json_match:
                return json.loads(json_match.group())
            return {"is_conventional": False, "type": None, "issue": "Ошибка парсинга"}
            
        except Exception as e:
            return {"is_conventional": False, "type": None, "issue": str(e)}
    
    def generate_summary(self, author: str, ratio: int, total_commits: int, conventional_count: int = 0) -> str:
        """Генерирует общую информацию для аудитора"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты аудитор. Опиши кратко имещуюся ситуацию по разработчику. Максимум 2 предложения. Без приветствий и подписей. Учитывай процент соответствия."
                    },
                    {
                        "role": "user",
                        "content": f"Разработчик {author}. У него {total_commits} коммитов, из них {ratio}% соответствуют Conventional Commits.{conventional_count} из {total_commits} коммитов написаны по стандарту. Напиши summary."
                    }
                ],
                temperature=0.7,
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] LLM failed: {e}")
            return f"Разработчик {author}: {conventional_count} из {total_commits} коммитов соответствуют Conventional Commits ({ratio}%)."


async def analyze():
    print("АНАЛИЗ КОММИТОВ ПРОЕКТА hub-test")
    print("")
    
    print("Загрузка данных из GitLab...")
    analytics = GitLabAnalyticsComplete()
    report = await analytics.generate_full_report(days=90)
    user_mapper = UserMapper()

    all_commits = []
    seen_ids = set()
    for branch in await analytics.get_all_branches():
        commits = await analytics.get_commits_for_branch(branch['name'], days=90, seen_ids=seen_ids)
        for commit in commits:
            all_commits.append({
                'author': commit.get('author_name', 'unknown'),
                'message': commit.get('title', '') or commit.get('message', '')
            })
    
    print(f"Всего коммитов: {len(all_commits)}")
    print("")
    
    commits_by_author = defaultdict(list)
    for commit in all_commits:
        normalized_author = user_mapper.normalize_author(commit['author'])
        commits_by_author[normalized_author].append(commit)

    analyzer = SimpleAnalyzer()
    print("")
    

    results = []
    
    # Анализ для каждого автора
    for author, commits in commits_by_author.items():
        print("=" * 50)
        print(f"Автор: {author}")
        print(f"Коммитов: {len(commits)}")
        print("")
        
        conventional_count = 0
        
        # Проверяем все коммиты
        for commit in commits:
            msg = commit['message']
            print(f"  Коммит: {msg[:60]}")
            
            result = analyzer.check_conventional_commit(msg)
            
            if result.get('is_conventional'):
                conventional_count += 1
                print(f"    -> OK (тип: {result.get('type', '?')})")
            else:
                issue = result.get('issue')
                if issue:
                    print(f"    -> НЕТ: {str(issue)[:50]}")
                else:
                    print(f"    -> НЕТ: Не соответствует стандарту")
        
        ratio = int(conventional_count / len(commits) * 100) if commits else 0
        print("")
        print(f"  Conventional Commits: {conventional_count}/{len(commits)} ({ratio}%)")
        
        if ratio < 50:
            print("  Рекомендация: Используйте формат feat: текст, fix: текст, docs: текст")
        
        print("")
        print("  Summary:")
        wish = analyzer.generate_summary(author, ratio, len(commits))
        print(f"    {wish}")
        
        print("")
        
        # Сохраняем результат
        results.append({
            'author': author,
            'commits': len(commits),
            'conventional': conventional_count,
            'ratio': ratio,
            'wish': wish
        })
    
    print("=" * 50)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 50)
    print("")
    
    for res in results:
        if res['ratio'] >= 70:
            status = "ХОРОШО"
        elif res['ratio'] >= 40:
            status = "УЛУЧШИТЬ"
        else:
            status = "ПЛОХО"
        print(f"{res['author']}: {res['ratio']}% соответствия ({status})")
    
    print("")
    print("Анализ завершен")


if __name__ == "__main__":
    asyncio.run(analyze())