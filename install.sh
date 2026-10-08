#!/bin/sh
# Okeanos: first install from GitHub, or update an existing install.
#
#   curl -fsSL https://raw.githubusercontent.com/mateusblm/okeanos-agent/main/install.sh | sh
#   sh install.sh [--agent claude|codex] [--uninstall] [--dry-run]
#
# Clones (or fast-forwards) the repo into ~/.local/share/okeanos and runs
# `bin/okeanos install` from there, which detects the agents on the PATH.
# OKEANOS_REPO overrides the source, OKEANOS_DIR the clone directory and
# OKEANOS_HOME_DIR the home directory.
set -eu

repo="${OKEANOS_REPO:-https://github.com/mateusblm/okeanos-agent.git}"
home="${OKEANOS_HOME_DIR:-$HOME}"
dir="${OKEANOS_DIR:-$home/.local/share/okeanos}"

for tool in git python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "okeanos: precisa de $tool no PATH." >&2; exit 1; }
done

if [ -d "$dir/.git" ]; then
  echo "Atualizando $dir"
  git -C "$dir" pull --ff-only --quiet
else
  echo "Clonando $repo em $dir"
  mkdir -p "$(dirname "$dir")"
  git clone --quiet "$repo" "$dir"
fi

exec python3 "$dir/bin/okeanos" install "$@"
