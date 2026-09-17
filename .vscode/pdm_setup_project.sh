#!/usr/bin/env bash
set -euo pipefail

# --- Discover paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Script directory: ${SCRIPT_DIR}"
echo "Repository directory: ${REPO_DIR}"

# Helper: add a directory to PATH if it exists and isn't already present
add_path_if_dir() {
  local d="$1"
  if [ -d "$d" ] && [[ ":$PATH:" != *":$d:"* ]]; then
    export PATH="$d:$PATH"
  fi
}

# Determine python major.minor (for macOS user site bin)
detect_py_mm() {
  local v=""
  if command -v python3 >/dev/null 2>&1; then
    v=$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)
  elif command -v python >/dev/null 2>&1; then
    v=$(python -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)
  fi
  echo "$v"
}

# Pre-populate PATH with common user install locations
PY_MM=$(detect_py_mm)
add_path_if_dir "${HOME}/.local/bin"                    # Unix/Linux default
if [ -n "$PY_MM" ]; then
  add_path_if_dir "${HOME}/Library/Python/${PY_MM}/bin"  # macOS default
fi

# --- Ensure PDM is available (with installer integrity verification) ---
ensure_pdm() {
  if command -v pdm >/dev/null 2>&1; then
    return 0
  fi

  # Try common user bin path on *nix
  if [ -d "${HOME}/.local/bin" ]; then
    export PATH="${HOME}/.local/bin:${PATH}"
  fi

  if command -v pdm >/dev/null 2>&1; then
    return 0
  fi

  echo "'pdm' not found. Installing PDM using official installer with checksum verification..."

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to install PDM. Please install curl and retry." >&2
    exit 1
  fi

  # Download installer and verify checksum
  INSTALLER_URL="https://pdm-project.org/install-pdm.py"
  SHA_URL="https://pdm-project.org/install-pdm.py.sha256"

  TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t pdm-install)"
  trap 'rm -rf "${TMP_DIR}"' EXIT
  (
    set -e
    cd "${TMP_DIR}"
    echo "Downloading installer to ${TMP_DIR}..."
    curl -sSLO "${INSTALLER_URL}"

    # Verify checksum using shasum/sha256sum, fallback to Python if unavailable
    if command -v shasum >/dev/null 2>&1; then
      echo "Verifying installer checksum with shasum..."
      curl -sSL "${SHA_URL}" | shasum -a 256 -c -
    elif command -v sha256sum >/dev/null 2>&1; then
      echo "Verifying installer checksum with sha256sum..."
      EXPECTED_HASH="$(curl -sSL "${SHA_URL}" | awk '{print $1}')"
      echo "${EXPECTED_HASH}  install-pdm.py" | sha256sum -c -
    else
      echo "No shasum/sha256sum found; verifying with Python..."
      if command -v python3 >/dev/null 2>&1; then PYTHON=python3; elif command -v python >/dev/null 2>&1; then PYTHON=python; else echo "python3 or python required" >&2; exit 1; fi
      "${PYTHON}" - <<'PY'
import hashlib, sys, urllib.request
installer = 'install-pdm.py'
sha_url = 'https://pdm-project.org/install-pdm.py.sha256'
expected = urllib.request.urlopen(sha_url).read().decode().strip().split()[0]
h = hashlib.sha256()
with open(installer,'rb') as f:
    for chunk in iter(lambda: f.read(8192), b''):
        h.update(chunk)
calc = h.hexdigest()
if calc != expected:
    print(f"Checksum mismatch: expected {expected}, got {calc}", file=sys.stderr)
    sys.exit(1)
print('Checksum OK')
PY
    fi

    # Run the installer after verification
    if command -v python3 >/dev/null 2>&1; then
      python3 install-pdm.py
    elif command -v python >/dev/null 2>&1; then
      python install-pdm.py
    else
      echo "python3 or python is required to run the installer." >&2
      exit 1
    fi
  )

  # Update PATH for current session (Unix + macOS locations)
  PY_MM=$(detect_py_mm)
  add_path_if_dir "${HOME}/.local/bin"
  if [ -n "$PY_MM" ]; then
    add_path_if_dir "${HOME}/Library/Python/${PY_MM}/bin"
  fi

  if ! command -v pdm >/dev/null 2>&1; then
    echo "'pdm' still not found after installation. Ensure ${HOME}/.local/bin is on PATH and retry." >&2
    exit 1
  fi
}

ensure_pdm

# --- Update PDM itself (non-fatal) ---
if ! pdm self update; then
  echo "Warning: 'pdm self update' failed; continuing..."
fi

# --- Move to repository root ---
cd "${REPO_DIR}"

# --- Ensure git submodules are checked out (e.g. bk_maya/bk_proxor) ---
# Without this the .prxc proxor parser silently fails to import and no
# proxor hologram is drawn. Safe to run repeatedly; no-op once populated.
if command -v git >/dev/null 2>&1 && [ -f "${REPO_DIR}/.gitmodules" ]; then
  echo "Initializing/updating git submodules (recursive)..."
  if ! git -C "${REPO_DIR}" submodule update --init --recursive; then
    echo "Warning: 'git submodule update --init --recursive' failed; continuing..." >&2
  fi
fi


PROJECT_NAME="blenderkit_addon"
PROJECT_DIR="${REPO_DIR}"
REQUIREMENTS_FILE="${PROJECT_DIR}/pyproject.toml"

echo "----------------------------------------"
echo "Processing project: ${PROJECT_NAME}"
echo "----------------------------------------"

echo "Project directory: ${PROJECT_DIR}"
cd "${PROJECT_DIR}"

# --- Ensure a virtual environment exists ---
# This will create a project venv if it doesn't already exist.
# It's safe to run multiple times.
if ! pdm venv create --with-pip >/dev/null 2>&1; then
  echo "Note: 'pdm venv create' did not create a new venv (it may already exist)."
fi

# --- Install dependencies ---
if [ -f "${REQUIREMENTS_FILE}" ]; then
  echo "Installing dependencies from pyproject.toml via PDM..."
  # Default: install main deps as defined in [project] and [dependency-groups] (default group only).
  # If you also want dev tools installed, uncomment the -G dev line below.
  if ! pdm install; then
    echo "Warning: 'pdm install' failed. Please review pyproject.toml and lock state." >&2
    exit 1
  fi
  # To include dev group as well, use:
  # pdm install -G dev
else
  echo "No pyproject.toml found in ${PROJECT_NAME}, skipping dependency installation."
fi

# --- Show environment info ---
echo "Virtual environment setup for ${PROJECT_NAME} completed successfully!"
echo "----------------------------------------"
echo "Virtual environment info:"
pdm info --env || true
echo "----------------------------------------"

# --- Set up sub-repo virtual environments ---
# bk_client and bk_proxor are git submodules with their OWN pyproject.toml and
# their OWN (stricter/different) ruff + pydoclint rulesets. They must be linted
# against their own dependencies, so each gets its own project-local .venv
# instead of sharing the addon's. Safe to run repeatedly.
for SUBREPO in bk_client bk_proxor; do
  SUBREPO_DIR="${REPO_DIR}/${SUBREPO}"
  if [ -f "${SUBREPO_DIR}/pyproject.toml" ]; then
    echo "----------------------------------------"
    echo "Setting up sub-repo: ${SUBREPO}"
    echo "----------------------------------------"
    (
      cd "${SUBREPO_DIR}"
      if ! pdm venv create --with-pip >/dev/null 2>&1; then
        echo "Note: venv for ${SUBREPO} may already exist."
      fi
      if ! pdm install; then
        echo "Warning: 'pdm install' failed for ${SUBREPO}; continuing..." >&2
      fi
    )
  else
    echo "No pyproject.toml in ${SUBREPO}, skipping."
  fi
done

echo "How to use the environment:"
echo "  pdm shell                     # activate the venv"
echo "  pdm run python -V             # run python from the venv"
echo "  pdm run black .               # run tools from the venv"
