FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["your-live-eye"]
CMD ["--help"]
