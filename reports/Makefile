PYTHON ?= python3
.PHONY: test check release
test:
	$(PYTHON) -m unittest discover -s tests -v
check:
	$(PYTHON) release.py --check
release:
	$(PYTHON) release.py --output dist
