from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import config as app_config

_api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    if api_key != app_config.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
