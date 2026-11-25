.PHONY: up down logs test

# Portable check (pure make, no shell syntax): docker compose needs a root .env
ifeq ($(wildcard .env),)
$(error Missing .env - create it with: cp .env.example .env   (then put your real keys in it))
endif

# Build and start the stack in the background.
up:
	docker compose up --build -d
	@echo Frontend: http://localhost:3000
	@echo Backend:  http://localhost:8000/health

down:
	docker compose down

logs:
	docker compose logs -f

# Runs the backend tests inside the image (LLM calls are mocked; no real API use).
test:
	docker compose run --rm --no-deps backend python -m pytest -q
