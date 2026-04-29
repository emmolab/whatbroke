#!/bin/sh
set -eu

PKG=whatbroke
PURGE_STATE=0

need_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "error: root privileges required (run as root or install sudo)" >&2
    exit 1
  fi
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

detect_package_kind() {
  id=""
  like=""
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    id="${ID:-}"
    like="${ID_LIKE:-}"
  fi
  tokens=" $id $like "

  case "$tokens" in
    *" rhel "*|*" fedora "*|*" centos "*|*" rocky "*|*" alma "*|*" suse "*|*" opensuse "*)
      if has_cmd rpm; then echo rpm; return; fi
      ;;
    *" debian "*|*" ubuntu "*)
      if has_cmd dpkg; then echo deb; return; fi
      ;;
  esac

  if has_cmd dnf || has_cmd yum || has_cmd zypper; then
    echo rpm
    return
  fi

  if has_cmd apt-get; then
    echo deb
    return
  fi

  if has_cmd rpm; then
    echo rpm
    return
  fi

  if has_cmd dpkg; then
    echo deb
    return
  fi

  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge-state)
      PURGE_STATE=1
      ;;
    -h|--help)
      cat <<'EOF'
whatbroke uninstall script

Usage:
  sh uninstall.sh [--purge-state]

Options:
  --purge-state   Also remove root-owned whatbroke state under /root/.local/share/whatbroke
EOF
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

purge_state() {
  [ "$PURGE_STATE" -eq 1 ] || return 0
  if [ -d /root/.local/share/whatbroke ]; then
    echo "Removing root-owned whatbroke state under /root/.local/share/whatbroke..."
    need_root rm -rf /root/.local/share/whatbroke
  fi
}

cleanup_python_artifacts() {
  for base in \
    /usr/lib/python3/dist-packages \
    /usr/local/lib/python3/dist-packages \
    /usr/lib/python3/site-packages \
    /usr/local/lib/python3/site-packages \
    /usr/lib/python*/site-packages \
    /usr/local/lib/python*/site-packages
  do
    for pkgdir in $base/whatbroke; do
      [ -e "$pkgdir" ] || continue
      echo "Cleaning leftover Python package files under $pkgdir..."
      need_root find "$pkgdir" -type d -name '__pycache__' -prune -exec rm -rf {} +
      need_root find "$pkgdir" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
      need_root rmdir --ignore-fail-on-non-empty "$pkgdir/checks" 2>/dev/null || true
      need_root rmdir --ignore-fail-on-non-empty "$pkgdir" 2>/dev/null || true
    done
  done
}

kind="$(detect_package_kind || true)"

if [ "$kind" = "deb" ] && has_cmd dpkg; then
  if dpkg -s "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via dpkg..."
    need_root dpkg -r "$PKG"
    cleanup_python_artifacts
    purge_state
    exit 0
  fi
fi

if [ "$kind" = "rpm" ] && has_cmd rpm; then
  if rpm -q "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via rpm..."
    need_root rpm -e "$PKG"
    cleanup_python_artifacts
    purge_state
    exit 0
  fi
fi

for pip_cmd in 'python3 -m pip' pip3 pip; do
  if sh -c "$pip_cmd show '$PKG'" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via $pip_cmd..."
    need_root sh -c "$pip_cmd uninstall -y '$PKG'"
    cleanup_python_artifacts
    purge_state
    exit 0
  fi
done

echo "whatbroke does not appear to be installed via the expected package manager on this host."
exit 1
