.PHONY: lint test format format-check ci

lint:
	pre-commit run --all-files --show-diff-on-failure
	pylint src/ config/ main.py --rcfile=.pylintrc --output-format=colorized --score=yes

test:
	pytest tests/ -v --cov=src

format:
	black --line-length 100 src/ tests/ config/ main.py

format-check:
	black --check --line-length 100 src/ tests/ config/ main.py

ci:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) test
