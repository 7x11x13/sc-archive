rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip freeze > requirements.txt