PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: docs

docs: ## Clean, render Markdown docs to HTML under docs_html/, and serve at http://localhost:8000
	rm -rf docs_html
	$(PYTHON) scripts/build_docs.py
	$(PYTHON) -m http.server --directory docs_html 8000
