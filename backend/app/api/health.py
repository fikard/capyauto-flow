from fastapi import APIRouter

from app.deps import get_adapter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    return await get_adapter().health()
