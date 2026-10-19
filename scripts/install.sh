#!/usr/bin/env bash
# Installs the `jiyuu` command with uv (https://docs.astral.sh/uv/), or removes it.
#
#   scripts/install.sh              install for the current user, in ~/.local/bin
#   scripts/install.sh --system     install for every user, in /usr/local/bin (uses sudo)
#   scripts/install.sh --uninstall  remove it (with --system: the system-wide one)
#
# Other options:
#   --source <path or URL>  what to install: a folder or a `git+https://…` URL; by default
#                           the repository this script is in
#   --no-client             do not download Flet's desktop client after installing
#
# jiyuu is installed in an environment of its own (`uv tool install`), with its
# dependencies held to the versions in this repository's `uv.lock`. Running the script
# again reinstalls jiyuu from the source, so it also updates an existing installation. It
# asks no questions, so it can be run unattended.
#
# jiyuu's window is drawn by Flet's desktop client, which Flet downloads into
# ~/.flet/client the first time it is needed, once per user. After a user install, this
# script downloads it straight away, so that the first `jiyuu <file>` needs no network.
#
# `UV_TOOL_DIR` and `UV_TOOL_BIN_DIR`, if already set, choose where a user install goes.
set -euo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source="$repository"
system=0
uninstall=0
client=1

usage() {
    sed -n '2,/--no-client/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --system) system=1 ;;
        --uninstall) uninstall=1 ;;
        --no-client) client=0 ;;
        --source)
            [[ $# -ge 2 ]] || { echo "--source needs a path or URL" >&2; exit 2; }
            source="$2"
            shift
            ;;
        -h | --help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if ! command -v uv > /dev/null; then
    echo "uv is needed: see https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

# The uv command line every step below runs: for a system-wide install, as root, with the
# tool, its executable and the Python it runs on all in folders every user can read.
if [[ $system -eq 1 ]]; then
    uv_command=(sudo env
        UV_TOOL_DIR=/opt/uv/tools
        UV_TOOL_BIN_DIR=/usr/local/bin
        UV_PYTHON_INSTALL_DIR=/opt/uv/python
        "$(command -v uv)")
else
    uv_command=(uv)
fi

if [[ $uninstall -eq 1 ]]; then
    if "${uv_command[@]}" tool list 2> /dev/null | grep -q '^jiyuu '; then
        "${uv_command[@]}" tool uninstall jiyuu
    else
        echo "jiyuu is not installed there; nothing to remove"
    fi
    exit 0
fi

constraints="$(mktemp)"
trap 'rm -f "$constraints"' EXIT
uv export --project "$repository" --frozen --no-dev --no-hashes --no-emit-project \
    --format requirements-txt --quiet --output-file "$constraints"
chmod a+r "$constraints"

# --force replaces an existing `jiyuu` executable; --reinstall-package rebuilds jiyuu from
# the source even when its version number has not changed.
"${uv_command[@]}" tool install --force --reinstall-package jiyuu --constraints "$constraints" "$source"

bin_dir="$("${uv_command[@]}" tool dir --bin)"
echo "jiyuu installed: $bin_dir/jiyuu"

# uv itself warns when $bin_dir is not on PATH.
if [[ $system -eq 0 ]]; then
    if [[ $client -eq 1 ]]; then
        "$(uv tool dir)/jiyuu/bin/python" -c "import flet_desktop; flet_desktop.ensure_client_cached()"
        echo "Flet's desktop client is in ~/.flet/client"
    fi
else
    echo "each user's first \`jiyuu <file>\` downloads Flet's desktop client into ~/.flet/client"
fi
