## Progress
- ⬜ Step 1: Python project setup
- ⬜ Step 2: Token bucket algorithm + tests
- ⬜ Step 3: Fixed window algorithm + tests
- ⬜ Step 4: Sliding window algorithm + tests
- ⬜ Step 5: FastAPI app with in-memory backend + tests
- ⬜ Step 6: Redis backend + tests
- ⬜ Step 7: Docker + Docker Compose
- ⬜ Step 8: GitHub Actions CI/CD
- ⬜ Step 9: AWS EC2 deployment
- ⬜ Step 10: Locust load testing
- ⬜ Step 11: README + architecture diagram

## Current Issues
- None

## Notes
- Python 3.13.12 on Windows 11
- Docker deferred to Step 7 (WSL approach, no Docker Desktop)
- AWS config deferred to Step 8
- Using Postman for API testing

## Project Spec
# Project: Rate Limiter as a Service

I'm a Senior Software Engineer with 7+ years of experience in C#/.NET, Vue.js, and AWS. I'm building this portfolio project to strengthen my resume for FAANG applications. I need your help building it end-to-end using Claude CLI as my coding partner.

## My Current Skill Level
- Strong: C#, .NET Core, REST APIs, SQL Server, Vue.js, JavaScript/TypeScript
- Familiar: Docker (local POC only), AWS (S3, CloudFront only), Kafka, ELK Stack
- Learning: Python (beginner — I know C# and Java so syntax transfers fast)
- No experience with: Redis, FastAPI, pytest, Locust, AWS Lambda/ECS, GitHub Actions

## What It Does
A distributed rate limiting service exposed as REST API. Supports token bucket, fixed window, and sliding window algorithms. Redis-backed with atomic Lua scripts for distributed state.

## Tech Stack
Python 3.11, FastAPI, Redis, Docker, Docker Compose, AWS EC2 (free tier), AWS ECR, GitHub Actions, pytest, Locust

## Architecture
- FastAPI app with rate limiting algorithms
- Redis for distributed state (counters, TTLs, sorted sets)
- Lua scripts for atomic operations in Redis
- Docker Compose (API + Redis containers)
- Deployed on AWS EC2 t2.micro (free tier) running Docker Compose
- CI/CD via GitHub Actions (test → build → push to ECR)
- Load tested with Locust

## Endpoints
- POST /api/v1/check — Check if request is allowed
- GET /api/v1/status/{key} — Get rate limit status
- POST /api/v1/rules — Create rate limit rule
- GET /api/v1/rules — List rules
- DELETE /api/v1/rules/{id} — Delete rule
- GET /api/v1/health — Health check

## Project Structure
```
rate-limiter/
  main.py
  config.py
  algorithms/
    token_bucket.py
    fixed_window.py
    sliding_window.py
  routers/
    check.py
    rules.py
  models/
    requests.py
    responses.py
  services/
    rate_limiter_service.py
  storage/
    redis_backend.py
    memory_backend.py
  tests/
    test_token_bucket.py
    test_fixed_window.py
    test_sliding_window.py
    test_api.py
    test_redis_backend.py
  locustfile.py
  Dockerfile
  docker-compose.yml
  .github/workflows/ci.yml
  requirements.txt
  README.md
```

## How I Want to Work

1. **Build incrementally** — one module at a time, test each module before moving to next
2. **Teach me as we go** — I'm new to Python, FastAPI, Redis. Explain concepts briefly when introducing something new
3. **Write production-quality code** — proper error handling, type hints, docstrings, clean architecture
4. **Write tests alongside code** — not as an afterthought
5. **Follow this build order:**
   - Step 1: Python project setup (venv, requirements.txt, project structure)
   - Step 2: Token bucket algorithm + tests
   - Step 3: Fixed window algorithm + tests
   - Step 4: Sliding window algorithm + tests
   - Step 5: FastAPI app with in-memory backend + tests
   - Step 6: Redis backend + tests
   - Step 7: Docker + Docker Compose
   - Step 8: GitHub Actions CI/CD
   - Step 9: AWS EC2 deployment
   - Step 10: Locust load testing + capture performance numbers
   - Step 11: README with architecture diagram and load test results

## Constraints
- Everything must run free or near-free (< $1 total)
- AWS free tier only (EC2 t2.micro, ECR)
- Must be publicly hostable
- Code should be scalable in architecture even if deployment is minimal

## Start Now
Begin with Step 1: Set up the Python project. Create the virtual environment, requirements.txt with all dependencies, and the folder structure. Then move to Step 2: implement the token bucket algorithm.
