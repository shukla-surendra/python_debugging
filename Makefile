PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: docs docs-clean docs-serve

docs: ## Render all Markdown docs to HTML under docs_html/
	$(PYTHON) scripts/build_docs.py

docs-clean: ## Remove generated HTML docs
	rm -rf docs_html

docs-serve: docs ## Build docs and serve them at http://localhost:8000
	$(PYTHON) -m http.server --directory docs_html 8000
