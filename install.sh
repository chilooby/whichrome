#!/usr/bin/env bash
# Whichrome installer (macOS / Linux / Git Bash)
#   curl -fsSL https://raw.githubusercontent.com/chilooby/whichrome/main/install.sh | bash
# or, from a clone:
#   ./install.sh
set -euo pipefail

REPO="${WHICHROME_REPO:-https://github.com/chilooby/whichrome.git}"
INSTALL_DIR="${WHICHROME_HOME:-$HOME/.whichrome}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/whichrome"
BIN_DIR="${WHICHROME_BIN:-$HOME/.local/bin}"

info() { printf 'whichrome: %s\n' "$1"; }

# 1. Source: run from a clone if we are in one, else clone/update.
#    BASH_SOURCE is unset when piped from curl, so guard it.
self="${BASH_SOURCE[0]:-}"
here=""
[ -n "$self" ] && here="$(cd "$(dirname "$self")" && pwd)"
if [ -n "$here" ] && [ -f "$here/bin/whichrome.py" ]; then
  src="$here"; info "using this clone: $src"
elif [ -d "$INSTALL_DIR/.git" ]; then
  src="$INSTALL_DIR"; info "updating $src"; git -C "$src" pull --ff-only >/dev/null
else
  info "cloning into $INSTALL_DIR"; git clone --depth 1 "$REPO" "$INSTALL_DIR" >/dev/null; src="$INSTALL_DIR"
fi

# 2. Find a Python that actually runs. On Windows, `python3` is often a Microsoft Store
#    stub that exits without doing anything, so test each candidate before trusting it.
PY=""
for candidate in python3 python py; do
  cmd="$(command -v "$candidate" 2>/dev/null || true)"
  [ -n "$cmd" ] || continue
  if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$cmd"; break
  fi
done
[ -n "$PY" ] || { echo "whichrome: needs Python 3.9+ on PATH (tried python3, python, py)." >&2; exit 1; }
info "python: $PY"

# 3. Native path for the skill, so the baked-in commands work outside Git Bash too.
native_src="$src"
if command -v cygpath >/dev/null 2>&1; then native_src="$(cygpath -m "$src")"; fi

# 4. Install the skill with the real path baked in.
mkdir -p "$SKILLS_DIR"
sed "s|<whichrome>|$native_src|g" "$src/SKILL.md" > "$SKILLS_DIR/SKILL.md"
info "skill installed -> $SKILLS_DIR/SKILL.md"

# 5. A `whichrome` launcher so the documented commands work verbatim.
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/whichrome" <<LAUNCHER
#!/usr/bin/env bash
exec "$PY" "$native_src/bin/whichrome.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/whichrome"
info "launcher installed -> $BIN_DIR/whichrome"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) info "note: $BIN_DIR is not on your PATH; add it or call $PY $native_src/bin/whichrome.py" ;;
esac

# 6. Register this computer and scan its Chrome profiles. --if-unset keeps a label you chose.
label="${WHICHROME_LABEL:-$(hostname)}"
"$PY" "$src/bin/whichrome.py" device --label "$label" --if-unset --scan >/dev/null
info "registered this computer and scanned its Chrome profiles"

# 7. Make the registry findable from anywhere. It is per-user data, kept out of the repo.
registry="${WHICHROME_REGISTRY:-$HOME/.whichrome-registry.json}"
line="export WHICHROME_REGISTRY=\"$registry\""
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  grep -q "WHICHROME_REGISTRY" "$rc" || { printf '\n# whichrome\n%s\n' "$line" >> "$rc"; info "added WHICHROME_REGISTRY to $(basename "$rc")"; }
done

echo
info "done. Ask Claude to use a browser and the skill will fire."
info "roster: whichrome nicknames"
