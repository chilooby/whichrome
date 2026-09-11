#!/usr/bin/env bash
# The plugin's skill is generated from the canonical root SKILL.md so the two never drift.
# Root SKILL.md keeps the <whichrome> placeholder that install.sh / install.ps1 substitute.
# The plugin copy uses ${CLAUDE_PLUGIN_ROOT}, which Claude Code substitutes at runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p skills/whichrome
sed 's|<whichrome>|${CLAUDE_PLUGIN_ROOT}|g' SKILL.md > skills/whichrome/SKILL.md
echo "built skills/whichrome/SKILL.md from SKILL.md"
