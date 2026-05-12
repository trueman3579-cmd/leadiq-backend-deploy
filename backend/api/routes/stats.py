"""
api/routes/stats.py — Pipeline statistics and stream health.

GET /api/stats/pipeline   → lead counts by stage, avg scores, stream lengths
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from backend.api.deps import CurrentUser, DbSession, StreamClient
from backend.api.schemas import PipelineStatsResponse, StageCount
from backend.shared.config import settings
from backend.shared.models import Lead

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/pipeline", response_model=PipelineStatsResponse)
async def pipeline_stats(
    session: DbSession,
    stream: StreamClient,
    user: CurrentUser,
) -> PipelineStatsResponse:
    # Lead counts
    total_result = await session.execute(select(func.count(Lead.id)))
    total = total_result.scalar() or 0

    hot_result = await session.execute(
        select(func.count(Lead.id)).where(Lead.final_score >= 80)
    )
    hot = hot_result.scalar() or 0

    warm_result = await session.execute(
        select(func.count(Lead.id)).where(Lead.final_score >= 60, Lead.final_score < 80)
    )
    warm = warm_result.scalar() or 0

    avg_result = await session.execute(select(func.avg(Lead.final_score)))
    avg_score = round(float(avg_result.scalar() or 0.0), 1)

    # By stage
    stage_result = await session.execute(
        select(Lead.stage, func.count(Lead.id), func.avg(Lead.final_score))
        .group_by(Lead.stage)
        .order_by(func.count(Lead.id).desc())
    )
    by_stage = [
        StageCount(stage=row[0], count=row[1], avg_score=round(row[2] or 0.0, 1))
        for row in stage_result.all()
    ]

    # Stream lengths
    stream_lengths: dict[str, int] = {}
    stream_names = [
        settings.STREAM_COLLECTED,
        settings.STREAM_ANALYZED,
        settings.STREAM_SCORED,
        settings.STREAM_RANKED,
    ]
    for s in stream_names:
        try:
            length = await stream._r.xlen(s)
            stream_lengths[s] = length
        except Exception:
            stream_lengths[s] = -1

    return PipelineStatsResponse(
        total_leads=total,
        hot_leads=hot,
        warm_leads=warm,
        avg_final_score=avg_score,
        by_stage=by_stage,
        collected_today=stream_lengths.get(settings.STREAM_COLLECTED, 0),
        analyzed_today=stream_lengths.get(settings.STREAM_ANALYZED, 0),
        stream_lengths=stream_lengths,
    )
