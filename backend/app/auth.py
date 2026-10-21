from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings


admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    scheme_name="AdminKey",
    description="Administrator key required to upload or delete documents.",
    auto_error=False,
)


def require_admin_key(
    settings: Annotated[Settings, Depends(get_settings)],
    supplied_key: Annotated[str | None, Security(admin_key_header)],
) -> None:
    """Keep library mutations private; public read and question routes stay open."""
    expected_key = settings.admin_api_key.get_secret_value().strip()
    if not expected_key:
        raise HTTPException(status_code=503, detail="Administrator access is not configured.")
    if supplied_key is None or not compare_digest(
        supplied_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing administrator key.")
