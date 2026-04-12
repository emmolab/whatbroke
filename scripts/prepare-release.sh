#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Prepare a whatbroke release commit + tag.

Usage:
  ./scripts/prepare-release.sh 0.4.0
  ./scripts/prepare-release.sh v0.4.0

What it does:
  - validates the requested version
  - updates pyproject.toml and whatbroke/__init__.py
  - creates commit: Release vX.Y.Z
  - creates annotated git tag: vX.Y.Z

Afterwards push both branch and tag:
  git push origin main --follow-tags

That tag push triggers .github/workflows/release.yml, which builds the
wheel/sdist/.deb/.rpm artifacts and creates or updates the matching
GitHub Release automatically.
USAGE
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VERSION_INPUT="${1:-}"
if [[ -z "$VERSION_INPUT" || "$VERSION_INPUT" == "-h" || "$VERSION_INPUT" == "--help" ]]; then
  usage
  [[ -n "$VERSION_INPUT" ]] && exit 0
  exit 1
fi

VERSION="${VERSION_INPUT#v}"
TAG="v${VERSION}"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.-]+)?$ ]]; then
  echo "error: expected a semantic version like 0.4.0 or v0.4.0, got: $VERSION_INPUT" >&2
  exit 1
fi

cd "$REPO_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "error: working tree is not clean; commit or stash changes first" >&2
  exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "error: tag already exists: $TAG" >&2
  exit 1
fi

CURRENT_VERSION="$(python3 - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(data['project']['version'])
PY
)"

if [[ "$CURRENT_VERSION" == "$VERSION" ]]; then
  echo "error: project is already at version $VERSION" >&2
  exit 1
fi

python3 - "$VERSION" <<'PY'
import pathlib, re, sys

version = sys.argv[1]

pyproject = pathlib.Path('pyproject.toml')
text = pyproject.read_text()
text, count = re.subn(
    r'(?m)^(version\s*=\s*")([^"]+)(")$',
    rf'\g<1>{version}\g<3>',
    text,
    count=1,
)
if count != 1:
    raise SystemExit('failed to update pyproject.toml version')
pyproject.write_text(text)

init_py = pathlib.Path('whatbroke/__init__.py')
text = init_py.read_text()
text, count = re.subn(
    r'(?m)^__version__\s*=\s*"[^"]+"$',
    f'__version__ = "{version}"',
    text,
    count=1,
)
if count != 1:
    raise SystemExit('failed to update whatbroke/__init__.py version')
init_py.write_text(text)
PY

git add pyproject.toml whatbroke/__init__.py
git commit -m "Release ${TAG}"
git tag -a "$TAG" -m "$TAG"

cat <<EOF2
Prepared ${TAG}.

Next:
  git push origin $(git branch --show-current) --follow-tags

The tag push will trigger the GitHub release workflow and publish fresh
release artifacts for ${TAG}.
EOF2
