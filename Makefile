PYTHON ?= python

.PHONY: test run-sample eval-sample
test:
	$(PYTHON) -m pytest

run-sample:
	$(PYTHON) -m datamate.cli run --data-dir data/samples --result-dir result/sample

eval-sample:
	$(PYTHON) -m datamate.cli eval result/sample/submission.jsonl data/samples/answers.jsonl
