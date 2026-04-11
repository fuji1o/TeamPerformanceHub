from fastapi import APIRouter
from datetime import datetime

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}