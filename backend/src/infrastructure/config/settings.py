import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "").strip()
    GITLAB_URL: str = os.getenv("GITLAB_URL", "https://gitlab.com").strip()
    
    GITLAB_PROJECT_IDS: List[str] = [
        pid.strip() for pid in os.getenv("GITLAB_PROJECT_IDS", "").split(",") if pid.strip()
    ]
    GITLAB_GROUP_ID: Optional[str] = os.getenv("GITLAB_GROUP_ID", "").strip() or None
    GITLAB_PROJECT_ID: Optional[str] = os.getenv("GITLAB_PROJECT_ID", "").strip() or None

    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    
    @property
    def is_llm_available(self) -> bool:
        """Доступность ллм"""
        return bool(self.DEEPSEEK_API_KEY)
    
    def get_project_ids(self) -> List[str]:
        """Список ID проектов для анализа"""
        if self.GITLAB_PROJECT_IDS:
            return self.GITLAB_PROJECT_IDS
        elif self.GITLAB_PROJECT_ID:
            return [self.GITLAB_PROJECT_ID]
        return []
    
    def __repr__(self) -> str:
        return f"Settings(GITLAB_URL={self.GITLAB_URL}, projects={self.get_project_ids()})"

settings = Settings()   