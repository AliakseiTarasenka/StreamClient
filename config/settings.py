"""
Configuration management using environment variables
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    # API Configuration
    max_connections: int = 100
    cache_ttl: int = 5  # seconds
    request_timeout: int = 30  # seconds

    # WebSocket Configuration
    enable_websocket: bool = False
    websocket_host: str = "localhost"
    websocket_port: int = 8765
    poll_interval: int = 2  # seconds for API polling

    # File Output Configuration
    output_path: str = "output"

    # Game Configuration
    game_duration: int = 25  # minutes

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text

    class Config:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False  # APP_NAME, app_name, or App_Name all map to the same variable
        extra = "allow"
