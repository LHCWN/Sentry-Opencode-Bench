#!/usr/bin/env bash
set -e

IMAGE_NAME="opencode-sentry-bench"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure required local directories exist for volume mounting
mkdir -p "${SCRIPT_DIR}/outputs" "${SCRIPT_DIR}/reports" "${SCRIPT_DIR}/workspaces"

# Build image if not present or requested
build_image() {
    echo "🔨 Building Docker image ${IMAGE_NAME}..."
    docker build -t "${IMAGE_NAME}" -f "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}"
    echo "✅ Image ${IMAGE_NAME} built successfully."
}

# Check if image exists
if [[ "$1" == "build" ]]; then
    build_image
    exit 0
fi

if [[ -z "$(docker images -q ${IMAGE_NAME} 2> /dev/null)" ]]; then
    build_image
fi

# Detect interactive TTY
DOCKER_FLAGS="-i"
if [ -t 0 ] && [ -t 1 ]; then
    DOCKER_FLAGS="-it"
fi

# Common volume mounts
VOLUMES=(
    -v "${SCRIPT_DIR}/benchmarks:/app/benchmarks"
    -v "${SCRIPT_DIR}/scripts:/app/scripts"
    -v "${SCRIPT_DIR}/outputs:/app/outputs"
    -v "${SCRIPT_DIR}/reports:/app/reports"
    -v "${SCRIPT_DIR}/workspaces:/app/workspaces"
)

# Mode routing
MODE="${1:-help}"

case "$MODE" in
    single)
        shift
        INSTANCE_ID="${1:-psf__requests-2317}"
        shift || true
        echo "🚀 Running single SWE-bench instance in Docker: ${INSTANCE_ID}"
        docker run --rm ${DOCKER_FLAGS} \
            --add-host=host.docker.internal:host-gateway \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            python benchmarks/swebench_runner.py \
                --instance-id "${INSTANCE_ID}" \
                --opencode-model "crazyrouter/deepseek-flash" \
                --opencode-variant high \
                --config "configs/providers/lmstudio_docker.yaml" \
                --check-interval 5 \
                --check-on-error \
                "$@"
        ;;

    batch)
        shift || true
        echo "🚀 Running 5-task Batch Benchmark (Base vs Sentry) in Docker..."
        docker run --rm ${DOCKER_FLAGS} \
            --add-host=host.docker.internal:host-gateway \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            python benchmarks/run_batch_benchmark.py \
                --tasks psf__requests-2317 pallets__flask-4045 pallets__flask-4992 pallets__flask-5063 psf__requests-1963 \
                --model "crazyrouter/deepseek-flash" \
                --variant high \
                --sentry-config "configs/providers/lmstudio_docker.yaml" \
                --output-dir "outputs/batch_deepseek_flash" \
                --max-steps 25 \
                "$@"
        ;;

    report)
        shift || true
        echo "📊 Generating HTML report in Docker..."
        docker run --rm ${DOCKER_FLAGS} \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            python scripts/generate_html_report.py "$@"
        ;;

    eval)
        shift
        INSTANCE_ID="${1:-psf__requests-2317}"
        shift || true
        PATCH_FILE="${1:-}"
        EXTRA_ARGS=()
        if [ -n "${PATCH_FILE}" ]; then
            EXTRA_ARGS+=(--patch-file "${PATCH_FILE}")
            shift || true
        fi
        echo "🧪 Evaluating patch for ${INSTANCE_ID} in Docker..."
        docker run --rm ${DOCKER_FLAGS} \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            python benchmarks/evaluator.py \
                --instance-id "${INSTANCE_ID}" \
                "${EXTRA_ARGS[@]}" \
                "$@"
        ;;

    eval-batch)
        shift || true
        BATCH_DIR="${1:-outputs/batch_deepseek_flash}"
        shift || true
        echo "🧪 Evaluating all runs in ${BATCH_DIR} in Docker..."
        docker run --rm ${DOCKER_FLAGS} \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            python benchmarks/evaluator.py \
                --batch-dir "${BATCH_DIR}" \
                "$@"
        ;;

    shell)
        shift || true
        echo "🐚 Opening interactive shell inside Docker container..."
        docker run --rm ${DOCKER_FLAGS} \
            --add-host=host.docker.internal:host-gateway \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            bash
        ;;

    run)
        shift
        docker run --rm ${DOCKER_FLAGS} \
            --add-host=host.docker.internal:host-gateway \
            "${VOLUMES[@]}" \
            "${IMAGE_NAME}" \
            "$@"
        ;;

    *)
        echo "Usage: ./run_in_docker.sh <command>"
        echo ""
        echo "Commands:"
        echo "  build                 Build or rebuild the Docker container image"
        echo "  single <instance_id>  Run OpenCode + Sentry on a single SWE-bench task"
        echo "  batch                 Run comparative benchmark (Base vs Sentry) across 5 tasks"
        echo "  eval <instance_id>    Evaluate patch correctness against hidden test_patch"
        echo "  eval-batch <dir>      Evaluate all runs in a batch output directory"
        echo "  report                Regenerate HTML report from results.json"
        echo "  shell                 Open bash shell inside the Docker container"
        echo "  run <cmd...>          Execute arbitrary command inside the container"
        echo ""
        echo "Examples:"
        echo "  ./run_in_docker.sh eval psf__requests-2317"
        echo "  ./run_in_docker.sh eval-batch outputs/batch_deepseek_flash"
        echo "  ./run_in_docker.sh batch --force"
        echo "  ./run_in_docker.sh shell"
        ;;
esac
