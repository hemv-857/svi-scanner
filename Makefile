.PHONY: setup test demo calibrate lint

setup:
	pip install -e ".[dev]"

test:
	pytest

demo:
	python -m sviscan.cli demo --paths 40000

calibrate:
	python -m sviscan.cli calibrate

lint:
	ruff check src tests
