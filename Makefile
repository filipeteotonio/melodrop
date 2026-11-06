PYTHON ?= python3

.PHONY: run test lint format coverage clean

run:
	$(PYTHON) -m melodrop

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

coverage:
	$(PYTHON) -m coverage run -m unittest discover -s tests -t .
	$(PYTHON) -m coverage report

clean:
	rm -rf .coverage htmlcov build dist *.egg-info .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
