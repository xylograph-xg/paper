PYTHON ?= $(if $(wildcard infrastructure/environments/test/bin/python),infrastructure/environments/test/bin/python,python3)
WEB_GPT_IMPORT_ROOT ?= $(abspath ../chatgpt_playwright)
.PHONY: test test-setup check
test-setup:
	python3 -m venv infrastructure/environments/test
	infrastructure/environments/test/bin/python -m pip install -r infrastructure/maintenance/requirements-test.txt
test:
	@$(PYTHON) -c 'import sys; sys.exit("测试需要 Python 3.11+；安装 infrastructure/maintenance/requirements-test.txt 后用 make test PYTHON=/对应环境/bin/python") if sys.version_info < (3, 11) else None'
	@$(PYTHON) -c 'import importlib.util,sys; missing=[m for m in ("pymupdf","PIL","playwright","sympy","antlr4") if importlib.util.find_spec(m) is None]; sys.exit("缺少测试依赖："+", ".join(missing)+"；先运行 make test-setup 或向指定 PYTHON 安装 infrastructure/maintenance/requirements-test.txt") if missing else None'
	PYTHONPATH="$(CURDIR)/infrastructure/bootstrap:$(CURDIR):$(WEB_GPT_IMPORT_ROOT):$(PYTHONPATH)" $(PYTHON) infrastructure/maintenance/test_runner.py
check:
	PYTHONPATH="$(CURDIR)/infrastructure/bootstrap:$(CURDIR):$(PYTHONPATH)" $(PYTHON) infrastructure/maintenance/check_subprojects.py
