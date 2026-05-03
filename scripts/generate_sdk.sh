#!/usr/bin/env bash
# Generate API client SDKs from the OpenAPI specification.
#
# Prerequisites:
#   - docker (for openapi-generator-cli)
#   - Running instance of the API (or an exported openapi.json)
#
# Usage:
#   ./scripts/generate_sdk.sh                  # Generate all SDKs
#   ./scripts/generate_sdk.sh python           # Python only
#   ./scripts/generate_sdk.sh typescript        # TypeScript only
#
# The generated SDKs are written to sdk/<language>/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SDK_DIR="${PROJECT_ROOT}/sdk"
OPENAPI_SPEC="${PROJECT_ROOT}/openapi.json"
GENERATOR_IMAGE="openapitools/openapi-generator-cli:v7.4.0"

# Fetch the OpenAPI spec from the running server (or use existing file)
fetch_spec() {
    local url="${API_URL:-http://localhost:8000}/api/v1/openapi.json"
    echo "Fetching OpenAPI spec from ${url}..."
    if curl -sf "${url}" -o "${OPENAPI_SPEC}"; then
        echo "Spec saved to ${OPENAPI_SPEC}"
    else
        if [ -f "${OPENAPI_SPEC}" ]; then
            echo "Warning: Could not fetch spec. Using existing file."
        else
            echo "Error: Could not fetch spec and no existing file found."
            echo "Start the server or set API_URL environment variable."
            exit 1
        fi
    fi
}

generate_python() {
    echo "Generating Python SDK..."
    mkdir -p "${SDK_DIR}/python"

    docker run --rm \
        -v "${PROJECT_ROOT}:/project" \
        -w /project \
        "${GENERATOR_IMAGE}" generate \
        -i /project/openapi.json \
        -g python \
        -o /project/sdk/python \
        --additional-properties=packageName=nxs_client \
        --additional-properties=projectName=nxs-client \
        --additional-properties=packageVersion=0.1.0 \
        --additional-properties=generateSourceCodeOnly=true

    echo "Python SDK generated at ${SDK_DIR}/python"
}

generate_typescript() {
    echo "Generating TypeScript SDK..."
    mkdir -p "${SDK_DIR}/typescript"

    docker run --rm \
        -v "${PROJECT_ROOT}:/project" \
        -w /project \
        "${GENERATOR_IMAGE}" generate \
        -i /project/openapi.json \
        -g typescript-fetch \
        -o /project/sdk/typescript \
        --additional-properties=npmName=@nxs/client \
        --additional-properties=npmVersion=0.1.0 \
        --additional-properties=supportsES6=true \
        --additional-properties=typescriptThreePlus=true

    echo "TypeScript SDK generated at ${SDK_DIR}/typescript"
}

generate_go() {
    echo "Generating Go SDK..."
    mkdir -p "${SDK_DIR}/go"

    docker run --rm \
        -v "${PROJECT_ROOT}:/project" \
        -w /project \
        "${GENERATOR_IMAGE}" generate \
        -i /project/openapi.json \
        -g go \
        -o /project/sdk/go \
        --additional-properties=packageName=nxs \
        --additional-properties=isGoSubmodule=true

    echo "Go SDK generated at ${SDK_DIR}/go"
}

# Main
fetch_spec

TARGET="${1:-all}"

case "${TARGET}" in
    python)
        generate_python
        ;;
    typescript|ts)
        generate_typescript
        ;;
    go)
        generate_go
        ;;
    all)
        generate_python
        generate_typescript
        generate_go
        ;;
    *)
        echo "Unknown target: ${TARGET}"
        echo "Usage: $0 [python|typescript|go|all]"
        exit 1
        ;;
esac

echo "SDK generation complete."
