PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: docs check

docs: ## Clean, render Markdown docs to HTML under docs_html/, and serve at http://localhost:8000
	rm -rf docs_html
	$(PYTHON) scripts/build_docs.py
	$(PYTHON) -m http.server --directory docs_html 8000

check: ## Validate all relative Markdown links, then build docs (no serve) - CI-friendly
	$(PYTHON) scripts/check_links.py
	rm -rf docs_html
	$(PYTHON) scripts/build_docs.py
