"""Resource ownership at the composition root."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import main
from config.settings import Settings


def test_dependency_construction_failure_closes_api_client(tmp_path):
    """Even a wiring failure happens inside the API client's protected lifetime."""

    async def scenario():
        client = SimpleNamespace(close=AsyncMock())
        error = RuntimeError("composition failed")
        with (
            patch(
                "main.Settings", return_value=Settings(_env_file=None, output_path=str(tmp_path))
            ),
            patch("main.APIClientPool", return_value=client),
            patch("main.create_live_session", side_effect=error),
        ):
            with pytest.raises(RuntimeError) as caught:
                await main.main()
        assert caught.value is error
        client.close.assert_awaited_once()

    asyncio.run(scenario())
