from pydantic_settings import BaseSettings
from pathlib import Path
import json
from typing import Dict, Any


class APIConfig(BaseSettings):
    """API configuration loaded from environment variables"""

    api_default_env: str = "test"
    api_default_url: str = "https://scores.frisbee.pl/test3/ext/watchlive.php/"
    api_default_headers: str = (
        '{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}'
    )

    class Config:
        env_file = Path(__file__).resolve().parents[3] / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "allow"

    @property
    def default_headers(self) -> Dict[str, Any]:
        """Parse the JSON string from environment into a dictionary"""
        return json.loads(self.api_default_headers)
