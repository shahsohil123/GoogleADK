.PHONY: install playground run deploy clean

install:
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

playground:
	.venv/bin/adk web .

run:
	.venv/bin/adk run agent/

deploy:
	.venv/bin/python deployment/deploy.py

clean:
	rm -rf .venv __pycache__ agent/__pycache__
