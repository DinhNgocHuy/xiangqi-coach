"""Export / backup of the local database."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import db

router = APIRouter(prefix="/data", tags=["data"])
KEEP_BACKUPS = 10


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


@router.get("/export")
def export(request: Request) -> JSONResponse:
    content = {"exported_at": datetime.now(UTC).isoformat(), "tables": db.export_json(request.app.state.db)}
    return JSONResponse(
        content, headers={"Content-Disposition": f'attachment; filename="xiangqi-coach-export-{_stamp()}.json"'}
    )


@router.post("/backup", status_code=201)
def backup(request: Request) -> dict[str, Any]:
    data_dir = request.app.state.settings.db_path.parent
    path = db.backup_to(request.app.state.db, data_dir / f"coach-backup-{_stamp()}.db")
    for old in sorted(data_dir.glob("coach-backup-*.db"))[:-KEEP_BACKUPS]:  # names sort by timestamp
        old.unlink(missing_ok=True)
    return {"path": str(path), "size_bytes": path.stat().st_size}
