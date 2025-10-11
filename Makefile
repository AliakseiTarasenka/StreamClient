.PHONY: lint test format

lint:
	pylint src/ config/ main.py --rcfile=.pylintrc --output-format=colorized --score=yes

test:
	pytest tests/ -v --cov=src

format:
	black --line-length 100 src/ tests/ config/ main.py

ci:
	$(MAKE) format
	$(MAKE) lint
	$(MAKE) test