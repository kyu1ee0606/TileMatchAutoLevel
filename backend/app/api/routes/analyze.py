"""Level analysis API routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from ...models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    BatchAnalyzeResultItem,
)
from ...core.analyzer import LevelAnalyzer
from ..deps import get_level_analyzer

router = APIRouter(prefix="/api", tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_level(
    request: AnalyzeRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> AnalyzeResponse:
    """
    Analyze a level and return difficulty metrics.

    Args:
        request: AnalyzeRequest with level_json.
        analyzer: LevelAnalyzer dependency.

    Returns:
        AnalyzeResponse with score, grade, metrics, and recommendations.
    """
    try:
        report = analyzer.analyze(request.level_json)
        return AnalyzeResponse(**report.to_dict())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Analysis failed: {str(e)}")


@router.post("/levels/batch-analyze", response_model=BatchAnalyzeResponse)
async def batch_analyze_levels(
    request: BatchAnalyzeRequest,
    analyzer: LevelAnalyzer = Depends(get_level_analyzer),
) -> BatchAnalyzeResponse:
    """
    Analyze multiple levels in batch.

    Args:
        request: BatchAnalyzeRequest with levels or level_ids.
        analyzer: LevelAnalyzer dependency.

    Returns:
        BatchAnalyzeResponse with results for each level.
    """
    results: List[BatchAnalyzeResultItem] = []

    if request.levels:
        # Analyze provided level JSONs
        for i, level_json in enumerate(request.levels):
            try:
                report = analyzer.analyze(level_json)
                results.append(BatchAnalyzeResultItem(
                    level_id=f"level_{i}",
                    score=report.score,
                    grade=report.grade.value,
                    metrics=report.metrics.to_dict(),
                ))
            except Exception as e:
                results.append(BatchAnalyzeResultItem(
                    level_id=f"level_{i}",
                    score=0,
                    grade="?",
                    metrics={"error": str(e)},
                ))
    elif request.level_ids and request.board_id:
        # TODO: Load levels from GBoost and analyze
        # This would require async loading from GBoost client
        raise HTTPException(
            status_code=501,
            detail="Loading levels from GBoost in batch is not yet implemented"
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Either 'levels' or 'level_ids' with 'board_id' must be provided"
        )

    return BatchAnalyzeResponse(results=results)
