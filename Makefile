.PHONY: test api stack web-dev web-test web-build clean

test:
	python -m pytest -q

api:
	python paper_api/server.py

stack:
	python paper_api/stackctl.py start

web-dev:
	cd web && npm run dev

web-test:
	cd web && npm run test

web-build:
	cd web && npm run build

clean:
	find . -name .DS_Store -delete
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache web/dist web/node_modules
