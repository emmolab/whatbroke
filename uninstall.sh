#!/bin/sh
set -eu

PKG=whatbroke

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

if has_cmd dpkg; then
  if dpkg -s "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via dpkg..."
    need_root dpkg -r "$PKG"
    exit 0
  fi
fi

if has_cmd rpm; then
  if rpm -q "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via rpm..."
    need_root rpm -e "$PKG"
    exit 0
  fi
fi

if has_cmd pip; then
  if pip show "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via pip..."
    need_root pip uninstall -y "$PKG"
    exit 0
  fi
fi

if has_cmd pip3; then
  if pip3 show "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via pip3..."
    need_root pip3 uninstall -y "$PKG"
    exit 0
  fi
fi

echo "whatbroke does not appear to be installed via dpkg, rpm, pip, or pip3 on this host."
exit 1
