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

kind="$(detect_package_kind || true)"

if [ "$kind" = "deb" ] && has_cmd dpkg; then
  if dpkg -s "$PKG" >/dev/null 2>&1; then
    echo "Uninstalling $PKG via dpkg..."
    need_root dpkg -r "$PKG"
    exit 0
  fi
fi

if [ "$kind" = "rpm" ] && has_cmd rpm; then
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

echo "whatbroke does not appear to be installed via the expected package manager on this host."
exit 1
