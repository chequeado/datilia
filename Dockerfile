FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml .

# Install production deps before copying source (better layer caching)
RUN uv sync --no-dev

COPY . .

EXPOSE 8080

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uv", "run", "gunicorn", "chequeado_contextualizer.wsgi:application", \
     "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "180"]
