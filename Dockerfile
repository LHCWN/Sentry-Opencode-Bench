FROM python:3.11-slim

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    ca-certificates \
    procps \
    iptables \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode CLI globally
RUN npm install -g opencode-ai

# Set working directory
WORKDIR /app

# Install base Python dependencies
RUN pip install --no-cache-dir --upgrade pip "setuptools<70" wheel && \
    pip install --no-cache-dir \
    datasets \
    huggingface_hub \
    pyyaml \
    tqdm \
    pytest \
    "werkzeug<3.0" \
    "jinja2<3.1" \
    itsdangerous \
    blinker \
    tomli \
    requests \
    pandas \
    numpy \
    mpmath \
    asgiref \
    sqlparse \
    pytz \
    attrs \
    docutils \
    roman \
    html5lib \
    packaging \
    more-itertools

# Backward compatibility for legacy python code (collections ABCs in Python 3.11, jinja2 filters)
RUN python3 -c "import site, pathlib; p = pathlib.Path(site.getsitepackages()[0]) / 'sitecustomize.py'; p.write_text('import collections, collections.abc\nfor attr in [\"MutableSet\", \"MutableMapping\", \"MutableSequence\", \"Mapping\", \"Sequence\", \"Set\", \"Iterable\", \"Callable\", \"Iterator\", \"Container\", \"Hashable\"]:\n    if not hasattr(collections, attr) and hasattr(collections.abc, attr):\n        setattr(collections, attr, getattr(collections.abc, attr))\ntry:\n    import jinja2\n    if hasattr(jinja2, \"pass_environment\") and not hasattr(jinja2, \"environmentfilter\"):\n        jinja2.environmentfilter = jinja2.pass_environment\nexcept Exception:\n    pass\n')"

# Copy project files
COPY pyproject.toml /app/
COPY Sentry /app/Sentry
COPY benchmarks /app/benchmarks
COPY configs /app/configs
COPY scripts /app/scripts
COPY README.md /app/

# Install Sentry in editable / development mode
RUN pip install --no-cache-dir -e .

# Pre-configure OpenCode with crazyrouter provider
RUN mkdir -p /root/.config/opencode
COPY docker/opencode.jsonc /root/.config/opencode/opencode.jsonc

# Set PYTHONPATH and default environment
ENV PYTHONPATH=/app

# Create required output and workspaces directories
RUN mkdir -p /app/outputs /app/reports /app/workspaces

# Default entrypoint / command
CMD ["python", "benchmarks/run_batch_benchmark.py", "--help"]
