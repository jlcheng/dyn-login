FROM python:3.12-slim AS fnox
ARG FNOX_VERSION=1.35.1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://github.com/jdx/fnox/releases/download/v${FNOX_VERSION}/fnox-x86_64-unknown-linux-musl.tar.gz" \
       | tar -xz -C /usr/local/bin fnox \
    && fnox --version

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv
COPY --from=fnox /usr/local/bin/fnox /usr/local/bin/fnox
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY dyn_login ./dyn_login
COPY fnox.toml gunicorn.conf.py ./
RUN uv sync --frozen --no-dev && useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8000
CMD ["fnox", "--non-interactive", "--no-daemon", "exec", "--", "gunicorn", "--config", "gunicorn.conf.py", "dyn_login:create_app()"]
