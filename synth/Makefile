.PHONY: all generate test report clean
PYTHON ?= python
all: generate test report

generate:
	$(PYTHON) -m src.cli generate

test:
	$(PYTHON) -m pytest -q tests

report:
	$(PYTHON) -m src.cli report

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree('out', ignore_errors=True)"
