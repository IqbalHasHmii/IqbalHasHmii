#!/usr/bin/env bash
# Installs the 13 Claude Code skills of this project at user level (~/.claude/skills), so
# every Claude Code project on this computer has them, including sessions started with
# `claude remote-control` or the Claude Desktop app.
#
#   Laptop (Mac / Linux / Git Bash):  bash install_skills.sh      (once)
#   Windows (cmd or double-click):    install_skills.cmd          (once)
#   Cloud sessions (claude.ai/code):  paste the `add ...` lines (with the add function) into the
#                                     environment's Setup script; every new session runs it.
#
# Needs Node.js (npx) and internet access to GitHub. Update later with: npx skills update -g -y
set -u

add() {
  npx -y skills add "$1" --skill "$2" -g -a claude-code -y --copy >/dev/null 2>&1 \
    && echo "ok      $2" || echo "FAILED  $2  ($1)"
}

add https://github.com/anthropics/skills                          frontend-design
add https://github.com/nextlevelbuilder/ui-ux-pro-max-skill       design
add https://github.com/binance/binance-skills-hub                 trading-signal
add https://github.com/affaan-m/ecc                               llm-trading-agent-security
add https://github.com/jeremylongshore/tons-of-skills-marketplace backtesting-trading-strategies
add https://github.com/vercel-labs/skills                         find-skills
add https://github.com/mattpocock/skills                          grill-me
add https://github.com/mattpocock/skills                          grilling
add https://github.com/vercel-labs/agent-browser                  agent-browser
add https://github.com/skills-shell/superpowers                   ai-image-generation
add https://github.com/microsoft/azure-skills                     azure-diagnostics
add https://github.com/designed-by-ai/skills                      design-mobile-apps
add https://github.com/101-skills/superpowers                     ai-video-generation

echo "Done. Restart Claude Code (or start a new session) to load the skills."
