import os
from typing import List, Dict, Optional
from dotenv import load_dotenv
import aiohttp
from gidgetlab.aiohttp import GitLabAPI

load_dotenv()


class ProjectManager:
    """Управление списком проектов для аналитики"""
    
    def __init__(self):
        self.token = os.getenv("GITLAB_TOKEN", "").strip()
        self.url = os.getenv("GITLAB_URL", "[gitlab.com](https://gitlab.com)").strip()
        self.group_id = os.getenv("GITLAB_GROUP_ID", "").strip() or None
        
        # Парсим список проектов из env
        project_ids_str = os.getenv("GITLAB_PROJECT_IDS", "").strip()
        self.configured_project_ids = [
            pid.strip() for pid in project_ids_str.split(",") if pid.strip()
        ]
        
        # Кэш проектов
        self._projects_cache: Optional[List[Dict]] = None
    
    async def get_all_projects(self, force_refresh: bool = False) -> List[Dict]:
        """Получает все доступные проекты"""
        if self._projects_cache and not force_refresh:
            return self._projects_cache
        
        projects = []
        
        async with aiohttp.ClientSession() as session:
            gl = GitLabAPI(session, self.token, url=self.url)
            
            # Если указан group_id — загружаем проекты группы
            if self.group_id:
                projects = await self._fetch_group_projects(gl)
            
            # Если указаны конкретные project_ids — добавляем их
            elif self.configured_project_ids:
                projects = await self._fetch_specific_projects(gl)
            
            # Иначе — все доступные проекты пользователя
            else:
                projects = await self._fetch_user_projects(gl)
        
        self._projects_cache = projects
        return projects
    
    async def _fetch_group_projects(self, gl: GitLabAPI) -> List[Dict]:
        """Загружает проекты из группы (включая подгруппы)"""
        projects = []
        try:
            params = {
                "include_subgroups": "true",
                "per_page": 100,
                "archived": "false"
            }
            async for project in gl.getiter(
                f"/groups/{self.group_id}/projects", 
                params=params
            ):
                projects.append(self._normalize_project(project))
        except Exception as e:
            print(f"[ERROR] Ошибка загрузки проектов группы {self.group_id}: {e}")
        return projects
    
    async def _fetch_specific_projects(self, gl: GitLabAPI) -> List[Dict]:
        """Загружает конкретные проекты по ID"""
        projects = []
        for pid in self.configured_project_ids:
            try:
                project = await gl.getitem(f"/projects/{pid}")
                projects.append(self._normalize_project(project))
            except Exception as e:
                print(f"[ERROR] Ошибка загрузки проекта {pid}: {e}")
        return projects
    
    async def _fetch_user_projects(self, gl: GitLabAPI) -> List[Dict]:
        """Загружает все проекты, доступные пользователю"""
        projects = []
        try:
            params = {
                "membership": "true",
                "per_page": 100,
                "archived": "false",
                "min_access_level": 30  # Developer и выше
            }
            async for project in gl.getiter("/projects", params=params):
                projects.append(self._normalize_project(project))
        except Exception as e:
            print(f"[ERROR] Ошибка загрузки проектов пользователя: {e}")
        return projects
    
    def _normalize_project(self, project: Dict) -> Dict:
        """Нормализует данные проекта"""
        return {
            "id": project["id"],
            "name": project["name"],
            "path": project["path"],
            "full_path": project["path_with_namespace"],
            "web_url": project["web_url"],
            "description": project.get("description", ""),
            "default_branch": project.get("default_branch", "main"),
            "namespace": project.get("namespace", {}).get("full_path", ""),
        }
    
    async def get_project_by_id(self, project_id: int) -> Optional[Dict]:
        """Получает проект по ID"""
        projects = await self.get_all_projects()
        return next((p for p in projects if p["id"] == project_id), None)
