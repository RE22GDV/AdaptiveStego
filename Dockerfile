# Reproducible environment for the experiments.
#
#   docker build -t adaptivestego .
#   docker run --rm adaptivestego selftest
#   docker run --rm -v "$PWD/results:/work/results" adaptivestego \
#       python experiments/benchmark.py --synthetic 12 --out results/main
#
# The image installs the pinned dependency set from requirements-lock.txt, so
# two builds of the same commit run the same code against the same libraries.
# The GUI is not available inside the container; use the CLI and the scripts.

FROM python:3.12-slim

# OpenCV needs these shared libraries even in its headless form.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY experiments ./experiments
COPY configs ./configs
COPY tests ./tests
RUN pip install --no-cache-dir --no-deps -e .

ENV PYTHONPATH=/work/src
ENTRYPOINT ["python", "-m", "adaptivestego"]
CMD ["--help"]
