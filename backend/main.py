from contextlib import asynccontextmanager

from src.interfaces.api.routes import projects
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.interfaces.api.routes import health, team, overview
from src.infrastructure.http_session import init_session, close_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_session()
    yield
    await close_session()


app = FastAPI(
    title="Team Performance Hub",
    description="Дашборд активности разработчиков на основе GitLab",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(team.router)
app.include_router(overview.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
