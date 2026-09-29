PY := .venv/bin/python

.PHONY: setup data app test eval report alerts

setup:            ## create the venv and install everything
	uv venv --python 3.11 .venv
	uv pip install --python $(PY) -e ".[ocr,rag,dev]"

data:             ## download the World Bank dataset (48 MB) and run the pipeline
	mkdir -p data/raw
	test -f data/raw/rpw_dataset_2011_2025_q3.xlsx || curl -L -o data/raw/rpw_dataset_2011_2025_q3.xlsx \
		https://datacatalogfiles.worldbank.org/ddh-published/0037898/DR0095523/rpw_dataset_2011_2025_q3.xlsx
	.venv/bin/fairsend pipeline

app:              ## run the web app on http://localhost:8501
	.venv/bin/fairsend app

test:
	$(PY) -m pytest -q

eval:             ## receipt + explainer evaluations (needs Ollama running), then eval/RESULTS.md
	$(PY) eval/receipts/evaluate.py --rules-only
	$(PY) eval/receipts/evaluate.py
	$(PY) eval/explainer/evaluate.py
	$(PY) eval/summarize.py

report:           ## global cost report -> reports/global_remittance_costs.md
	.venv/bin/fairsend report

alerts:           ## refresh FX and run the daily alert check once
	.venv/bin/fairsend fx && .venv/bin/fairsend alerts
