FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8100
# app:app, not marketplace.server:app -- M4a added a second MCP server
# (booking) and app.py mounts both into one process. Marketplace keeps its
# original /mcp and /health paths, so MCP_MARKETPLACE_URL and the compose
# healthcheck are unchanged.
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
