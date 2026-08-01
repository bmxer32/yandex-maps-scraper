"""
Роуты отбора клиентов.

POST /api/prospects/scan     — оценить пачку организаций (три ступени)
GET  /api/prospects/verdicts — забрать уже посчитанные по ключам сайтов
GET  /api/prospects/config   — работает ли третья ступень (задан ли ключ)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from ..models.prospect import ProspectVerdict, ScanRequest, ScanResponse
from ..services import prospect_service, site_verdict

router = APIRouter(prefix="/api/prospects", tags=["prospects"])


@router.get("/config")
async def prospects_config() -> dict:
    """Что доступно: механика и проба есть всегда, вердикт модели — по ключу."""
    return {"llm_enabled": site_verdict.enabled(), "model": None}


@router.post("/scan", response_model=ScanResponse)
async def scan(req: ScanRequest) -> ScanResponse:
    """Оценить организации: тип ссылки, дубли, проба сайта, вердикт модели."""
    try:
        verdicts, classified, quota_hit = await prospect_service.scan(
            req.items, refresh=req.refresh
        )
    except Exception as exc:
        logger.exception("Сканирование сорвалось")
        raise HTTPException(status_code=500, detail=f"Не удалось оценить: {exc}") from exc

    return ScanResponse(
        items=verdicts,
        classified=classified,
        llm_enabled=site_verdict.enabled(),
        quota_hit=quota_hit,
    )


@router.get("/verdicts", response_model=list[ProspectVerdict])
async def verdicts(site: list[str] = Query(default=[])) -> list[ProspectVerdict]:
    """Вердикты из кэша по ключам сайтов — чтобы не пересчитывать при возврате."""
    if not site:
        return []
    cached = await prospect_service.load_cached(site)
    return list(cached.values())
