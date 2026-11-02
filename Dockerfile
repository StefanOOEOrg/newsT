# One image for every command of the package: the CLI selects the command at run time.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

# The wheel needs pyproject.toml, VERSION, src/ and the files its metadata names.
COPY pyproject.toml VERSION README.md LICENSE ./
COPY src ./src
COPY sql ./sql

RUN uv pip install --system --no-cache . && rm -rf /root/.cache/uv

# ``python -m newstrading.cli`` with a command appended; ``docker run <image> notify``
# replaces the default command.
ENTRYPOINT ["python", "-m", "newstrading.cli"]
CMD ["collect"]
