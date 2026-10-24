.PHONY: lint typecheck test test-live format format-check ci

lint:
	pre-commit run --all-files --show-diff-on-failure
	pylint src/ config/ main.py --rcfile=.pylintrc --output-format=colorized --score=yes

typecheck:
	python -m mypy src/ config/ main.py --ignore-missing-imports

test:
	pytest tests/ -v --cov=src

test-live:
	pytest -v -W error \
		tests/unit/test_live_session.py \
		tests/unit/test_main.py \
		tests/unit/test_signals.py \
		tests/unit/test_game_clock.py \
		tests/unit/test_streamer.py \
		tests/integration/test_integration.py \
		tests/integration/test_live_mode.py \
		tests/integration/test_live_outputs.py \
		tests/integration/test_websocket_server.py

format:
	black --line-length 100 src/ tests/ config/ main.py

format-check:
	black --check --line-length 100 src/ tests/ config/ main.py

ci:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
