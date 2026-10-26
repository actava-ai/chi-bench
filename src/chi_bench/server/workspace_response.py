"""Stream a pinned workspace file without following mutable path aliases."""

from pathlib import Path
from urllib.parse import quote

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from chi_bench.core.models import WorkspaceArtifact
from chi_bench.core.workspace_files import open_workspace_file


def workspace_file_response(
    root: Path, path: Path, artifact: WorkspaceArtifact
) -> StreamingResponse:
    stream = open_workspace_file(root, path)

    def chunks():
        with stream:
            while block := stream.read(64 * 1024):
                yield block

    return StreamingResponse(
        chunks(),
        media_type=artifact.mime_type,
        headers={"Content-Disposition": "inline; filename*=utf-8''" + quote(artifact.filename)},
        background=BackgroundTask(stream.close),
    )
