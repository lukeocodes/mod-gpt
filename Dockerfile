FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install uv

COPY . .

RUN uv sync --frozen

CMD ["uv", "run", "bot"]
