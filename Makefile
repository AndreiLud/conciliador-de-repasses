PY ?= python

.PHONY: all data reconcile offline rules test app site check

all:            ## generate data, reconcile with the local model (cache first), evaluate and export
	$(PY) run_all.py

offline:        ## same, replaying llm_cache/ only (no model server needed)
	$(PY) run_all.py --offline

rules:          ## rules only, no language model
	$(PY) run_all.py --ai off

data:
	$(PY) -m src.generator.generate

test:
	$(PY) -m pytest

app:
	streamlit run app/streamlit_app.py

site:           ## serve the static site on http://localhost:8000
	cd docs && $(PY) -m http.server 8000

check:          ## text checks over site, READMEs and sample letters
	$(PY) -m src.export.check_texts
