import aiofiles
from pathlib import Path
from typing import Dict


class AsyncFileManager:
    """Handles all file I/O operations"""

    def __init__(self, base_path: str = "output"):
        self.base_path = Path(base_path)
        self._ensure_base_directory()

    def _ensure_base_directory(self) -> None:
        """Ensure base output directory exists"""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_full_path(self, filename: str) -> Path:
        """Get full path for a file"""
        return self.base_path / filename

    def _ensure_directory(self, filepath: Path) -> None:
        """Ensure directory exists for file path"""
        directory = filepath.parent
        if directory != self.base_path:
            directory.mkdir(parents=True, exist_ok=True)

    async def write_text(self, filename: str, content: str) -> None:
        """Write text content to file"""
        filepath = self._get_full_path(filename)
        self._ensure_directory(filepath)

        async with aiofiles.open(filepath, "w", encoding="utf-8") as file:
            await file.write(content)

    async def write_roster(self, filename: str, players: Dict[str, str]) -> None:
        """Write team roster to file"""
        filepath = self._get_full_path(filename)
        self._ensure_directory(filepath)

        async with aiofiles.open(filepath, "w", encoding="utf-8") as file:
            for player_id, player_name in players.items():
                await file.write(f"{player_id}: {player_name}\n")

    def delete_file(self, filename: str) -> None:
        """Delete file if it exists"""
        filepath = self._get_full_path(filename)
        if filepath.exists():
            filepath.unlink()

