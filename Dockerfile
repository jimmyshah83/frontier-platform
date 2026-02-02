FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/loan_processor/ ./loan_processor/

# Expose port for HTTP server
EXPOSE 8000

# Run the HTTP MCP server
CMD ["uv", "run", "python", "-m", "loan_processor.local_mcp_server"]
