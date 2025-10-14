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

    async def read_text(self, filename: str) -> str:
        """Read text content from file"""
        filepath = self._get_full_path(filename)

        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        async with aiofiles.open(filepath, "r", encoding="utf-8") as file:
            return await file.read()

    async def append_text(self, filename: str, content: str) -> None:
        """Append text content to file"""
        filepath = self._get_full_path(filename)
        self._ensure_directory(filepath)

        async with aiofiles.open(filepath, "a", encoding="utf-8") as file:
            await file.write(content)

    def file_exists(self, filename: str) -> bool:
        """Check if file exists"""
        return self._get_full_path(filename).exists()

    def delete_file(self, filename: str) -> None:
        """Delete file if it exists"""
        filepath = self._get_full_path(filename)
        if filepath.exists():
            filepath.unlink()

    def list_files(self, pattern: str = "*") -> list:
        """List files matching pattern"""
        return [f.name for f in self.base_path.glob(pattern) if f.is_file()]
