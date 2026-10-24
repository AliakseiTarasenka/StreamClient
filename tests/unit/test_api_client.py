"""HTTP, TLS, retry, and cache contracts without remote network access."""

import asyncio
from pathlib import Path
import ssl
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
import pytest

from src.infrastructure.api.client import APIClient, APIClientPool, CacheManager, ResilientAPIClient


def test_posts_form_data_headers_timeout_and_closes_transport():
    async def scenario():
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, text="schedule")

        transport = httpx.MockTransport(handle)
        with patch.object(transport, "aclose", wraps=transport.aclose) as close:
            async with APIClient(
                "https://scores.example/watch",
                headers={"X-Test": "form"},
                timeout=7,
                transport=transport,
            ) as client:
                assert await client.post({"action": "games", "date": "2026-10-24"}) == "schedule"
            close.assert_awaited_once()
        request = requests[0]
        assert request.method == "POST"
        assert str(request.url) == "https://scores.example/watch"
        assert request.headers["X-Test"] == "form"
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert parse_qs(request.content.decode()) == {
            "action": ["games"],
            "date": ["2026-10-24"],
        }
        assert request.extensions["timeout"]["read"] == 7

    asyncio.run(scenario())


def test_cache_hit_bypass_invalidation_and_empty_response():
    async def scenario():
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, text="")

        async with APIClientPool(
            "https://scores.example/watch", transport=httpx.MockTransport(handle)
        ) as client:
            assert await client.post({"game": 1, "action": "events"}) == ""
            assert await client.post({"action": "events", "game": 1}) == ""
            assert len(requests) == 1
            await client.post({"game": 1, "action": "events"}, use_cache=False)
            assert len(requests) == 2
            await client.post({"game": 1, "action": "events"})
            assert len(requests) == 2
            client.invalidate_cache('"game": 1')
            await client.post({"game": 1, "action": "events"})
            assert len(requests) == 3
            assert client.get_cache_stats() == {"size": 1, "ttl_seconds": 5}
        assert client.get_cache_stats()["size"] == 0

    asyncio.run(scenario())


def test_cache_uses_monotonic_expiry_and_preserves_other_keys():
    with patch("src.infrastructure.api.client.monotonic", return_value=10) as clock:
        cache = CacheManager(ttl_seconds=5)
        cache.set("game:1", "one")
        cache.set("game:2", "two")
        clock.return_value = 14.9
        assert cache.get("game:1") == "one"
        cache.invalidate("game:2")
        assert cache.get("game:2") is None
        clock.return_value = 15
        assert cache.get("game:1") is None
        assert cache.size() == 0


def test_http_errors_are_not_cached_and_resources_close_on_failure():
    async def scenario():
        responses = iter([httpx.Response(503), httpx.Response(200, text="recovered")])
        async with APIClientPool(
            "https://scores.example/watch", transport=httpx.MockTransport(lambda _: next(responses))
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.post({"game": 1})
            assert client.get_cache_stats()["size"] == 0
            assert await client.post({"game": 1}) == "recovered"

        transport = httpx.MockTransport(lambda _: httpx.Response(500))
        with patch.object(transport, "aclose", wraps=transport.aclose) as close:
            with pytest.raises(httpx.HTTPStatusError):
                async with APIClient("https://scores.example", transport=transport) as failing:
                    await failing.post({})
            close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("recover", [True, False])
def test_resilient_client_retries_http_errors_and_propagates_exhaustion(recover):
    async def scenario():
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(200 if recover and len(requests) == 3 else 503, text="result")

        with patch("src.infrastructure.api.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            async with ResilientAPIClient(
                "https://scores.example", transport=httpx.MockTransport(handle)
            ) as client:
                if recover:
                    assert await client.post({"game": 1}) == "result"
                    assert await client.post({"game": 1}) == "result"
                else:
                    with pytest.raises(httpx.HTTPStatusError):
                        await client.post({"game": 1})
                    assert client.get_cache_stats()["size"] == 0
            assert len(requests) == 3
            assert [call.args[0] for call in sleep.await_args_list] == [1, 2]

    asyncio.run(scenario())


def test_resilient_client_does_not_retry_cancellation():
    async def scenario():
        def handle(_request):
            raise asyncio.CancelledError

        with patch("src.infrastructure.api.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            async with ResilientAPIClient(
                "https://scores.example", transport=httpx.MockTransport(handle)
            ) as client:
                with pytest.raises(asyncio.CancelledError):
                    await client.post({})
            sleep.assert_not_awaited()

    asyncio.run(scenario())


def test_resilient_client_retries_connection_errors():
    async def scenario():
        requests = []

        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                raise httpx.ConnectError("connection interrupted", request=request)
            return httpx.Response(200, text="recovered")

        with patch("src.infrastructure.api.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            async with ResilientAPIClient(
                "https://scores.example", transport=httpx.MockTransport(handle)
            ) as client:
                assert await client.post({}) == "recovered"
            assert len(requests) == 2
            sleep.assert_awaited_once_with(1)

    asyncio.run(scenario())


def test_default_tls_rejects_self_signed_local_server(monkeypatch):
    """Exercise the actual default HTTPX TLS path, rather than inspect constructor flags."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")

    async def scenario():
        fixtures = Path(__file__).parents[1] / "fixtures" / "tls"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(fixtures / "server.crt", fixtures / "server.key")

        async def respond(_reader, writer):
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=context)
        async with server:
            port = server.sockets[0].getsockname()[1]
            async with APIClient(f"https://127.0.0.1:{port}", timeout=2) as client:
                with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                    await client.post({"game": 1})

    asyncio.run(scenario())
