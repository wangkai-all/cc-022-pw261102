from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import MaskingError, RuleValidationError, SourceDataError
from .service import GenerationFailed, MaskingService, ValidationFailure
from .settings import Settings


class RulesPayload(BaseModel):
    rules: dict[str, Any]


class PreviewPayload(RulesPayload):
    limit: int = 5


def create_app(settings: Settings | None = None, service: MaskingService | None = None) -> FastAPI:
    settings = settings or Settings.default()
    service = service or MaskingService(settings)

    app = FastAPI(
        title="MaskFlow 数据脱敏工作台",
        version="1.0.0",
        description="确定性的跨表数据脱敏、预览、校验与原子导出",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "seed": service.settings.seed_status()}

    @app.get("/api/bootstrap")
    def bootstrap() -> dict:
        try:
            return service.bootstrap()
        except SourceDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/rules/validate")
    def validate_rules_endpoint(payload: RulesPayload) -> dict:
        try:
            return service.validate_document(payload.rules)
        except SourceDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/preview")
    def preview_endpoint(payload: PreviewPayload) -> dict:
        try:
            return service.preview(payload.rules, payload.limit)
        except ValidationFailure as exc:
            raise HTTPException(
                status_code=422,
                detail={"kind": "rules", "valid": False, **exc.report},
            ) from exc
        except SourceDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (MaskingError, RuleValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"kind": "masking", "valid": False, "errors": [str(exc)]},
            ) from exc

    @app.post("/api/generate")
    def generate_endpoint(payload: RulesPayload) -> dict:
        try:
            return service.generate(payload.rules)
        except ValidationFailure as exc:
            raise HTTPException(
                status_code=422,
                detail={"kind": "rules", "valid": False, **exc.report},
            ) from exc
        except GenerationFailed as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "kind": "checks",
                    "valid": False,
                    "job_id": exc.job_id,
                    "errors": [str(exc)],
                    "checks": exc.checks,
                },
            ) from exc
        except SourceDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (MaskingError, RuleValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"kind": "masking", "valid": False, "errors": [str(exc)]},
            ) from exc

    @app.get("/api/jobs")
    def list_jobs() -> dict:
        return {"jobs": service.list_jobs(), "seed": service.settings.seed_status()}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        try:
            return service.load_job(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.get("/api/jobs/{job_id}/download/{filename}")
    def download(job_id: str, filename: str) -> FileResponse:
        try:
            path = service.download_path(job_id, filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="文件不存在") from exc
        media_types = {
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
        }
        return FileResponse(
            path,
            media_type=media_types.get(path.suffix, "application/octet-stream"),
            filename=path.name,
        )

    dist = Path(settings.root) / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")

    return app


app = create_app()
