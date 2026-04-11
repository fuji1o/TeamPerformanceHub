from fastapi import APIRouter, HTTPException
from src.interfaces.api.schemas.response import ProjectInfo, ProjectListResponse
from src.infrastructure.project_manager import ProjectManager

router = APIRouter(tags=["projects"])
project_manager = ProjectManager()


@router.get("/api/projects", response_model=ProjectListResponse)
async def get_projects():
    """Список всех доступных проектов"""
    projects = await project_manager.get_all_projects()
    return ProjectListResponse(
        projects=[ProjectInfo(**p) for p in projects],
        total=len(projects)
    )


@router.get("/api/projects/{project_id}/info")
async def get_project_info(project_id: int):
    """Информация о конкретном проекте"""
    project = await project_manager.get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return projectcd