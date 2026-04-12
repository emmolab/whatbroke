#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="${WHATBROKE_REPO:-emmolab/whatbroke}"
API_BASE="https://api.github.com/repos/${REPO_SLUG}"
TMP_DIR=""
KEEP_TEMP="${WHATBROKE_KEEP_TEMP:-0}"

usage() {
  cat <<'EOF'
whatbroke install/upgrade script

Usage:
  curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash -s -- --version v0.3.2
  curl -fsSL https://raw.githubusercontent.com/emmolab/whatbroke/main/install.sh | bash -s -- --repo owner/repo

Options:
  --version TAG   Install a specific tag instead of the latest release
  --repo SLUG     Override GitHub repository slug (default: emmolab/whatbroke)
  --dry-run       Print the chosen asset URL without installing
  --help          Show this help
EOF
}

log() { printf '[whatbroke-install] %s\n' "$*"; }
fail() { printf '[whatbroke-install] ERROR: %s\n' "$*" >&2; exit 1; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "Required command missing: $1"; }

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" && "$KEEP_TEMP" != "1" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

read_os_release() {
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    echo "${ID:-}" "${ID_LIKE:-}"
  else
    echo "" ""
  fi
}

detect_package_kind() {
  local id like tokens
  read -r id like < <(read_os_release)
  tokens=" $id $like "

  if [[ "$tokens" == *" rhel "* || "$tokens" == *" fedora "* || "$tokens" == *" centos "* || "$tokens" == *" rocky "* || "$tokens" == *" alma "* || "$tokens" == *" suse "* || "$tokens" == *" opensuse "* ]]; then
    if command -v rpm >/dev/null 2>&1; then
      echo rpm
      return
    fi
  fi

  if [[ "$tokens" == *" debian "* || "$tokens" == *" ubuntu "* ]]; then
    if command -v dpkg >/dev/null 2>&1; then
      echo deb
      return
    fi
  fi

  if command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1 || command -v zypper >/dev/null 2>&1; then
    echo rpm
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    echo deb
    return
  fi

  if command -v rpm >/dev/null 2>&1; then
    echo rpm
    return
  fi

  if command -v dpkg >/dev/null 2>&1; then
    echo deb
    return
  fi

  return 1
}

VERSION="latest"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || fail "--version requires a value"
      VERSION="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || fail "--repo requires a value"
      REPO_SLUG="$2"
      API_BASE="https://api.github.com/repos/${REPO_SLUG}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

need_cmd uname
need_cmd mktemp
need_cmd python3

if command -v curl >/dev/null 2>&1; then
  fetch() {
    curl -fsSL "$1"
  }
  download() {
    curl -fL -o "$2" "$1"
  }
elif command -v wget >/dev/null 2>&1; then
  fetch() {
    wget -qO- "$1"
  }
  download() {
    wget -qO "$2" "$1"
  }
else
  fail 'curl or wget is required'
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  fail 'This installer currently supports Linux only'
fi

PACKAGE_KIND="$(detect_package_kind)" || fail 'Unsupported Linux distribution: could not determine deb vs rpm packaging'
PKG_EXT=""
INSTALL_CMD=()

if [[ "$PACKAGE_KIND" == "deb" ]]; then
  PKG_EXT=".deb"
  INSTALL_CMD=(dpkg -i)
else
  PKG_EXT=".rpm"
  INSTALL_CMD=(rpm -Uvh)
fi

release_endpoint="$API_BASE/releases/latest"
if [[ "$VERSION" != "latest" ]]; then
  release_endpoint="$API_BASE/releases/tags/$VERSION"
fi

log "Resolving release metadata for ${REPO_SLUG} (${VERSION})"
release_json="$(fetch "$release_endpoint")" || fail 'Could not fetch release metadata from GitHub'

asset_info="$(RELEASE_JSON="$release_json" python3 - "$PKG_EXT" <<'PY'
import json, os, sys
ext = sys.argv[1]
release = json.loads(os.environ['RELEASE_JSON'])
assets = release.get('assets', [])
for asset in assets:
    url = asset.get('browser_download_url', '')
    name = asset.get('name', '')
    if name.endswith(ext):
        print(name)
        print(url)
        break
else:
    sys.exit(1)
PY
)" || fail "No ${PKG_EXT} asset found in the selected release"

asset_name="$(printf '%s\n' "$asset_info" | sed -n '1p')"
asset_url="$(printf '%s\n' "$asset_info" | sed -n '2p')"

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '%s\n' "$asset_url"
  exit 0
fi

TMP_DIR="$(mktemp -d)"
pkg_path="$TMP_DIR/$asset_name"

log "Downloading $asset_name"
download "$asset_url" "$pkg_path" || fail 'Package download failed'

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    log "Escalating with sudo for package installation"
    sudo "${INSTALL_CMD[@]}" "$pkg_path"
  else
    fail 'Root privileges are required to install the package (sudo not found)'
  fi
else
  "${INSTALL_CMD[@]}" "$pkg_path"
fi

log "Installed/updated whatbroke from ${asset_name}"
log "Run: whatbroke --version"
