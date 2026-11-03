@echo off
rem Installs the 13 Claude Code skills of this project at user level
rem (%USERPROFILE%\.claude\skills), so every Claude Code project on this Windows computer has
rem them, including sessions started with "claude remote-control" or the Claude Desktop app.
rem Needs Node.js (npx) and internet access to GitHub. Run once: double-click this file, or
rem type install_skills.cmd in a terminal. Update later with: npx skills update -g -y

call :add https://github.com/anthropics/skills frontend-design
call :add https://github.com/nextlevelbuilder/ui-ux-pro-max-skill design
call :add https://github.com/binance/binance-skills-hub trading-signal
call :add https://github.com/affaan-m/ecc llm-trading-agent-security
call :add https://github.com/jeremylongshore/tons-of-skills-marketplace backtesting-trading-strategies
call :add https://github.com/vercel-labs/skills find-skills
call :add https://github.com/mattpocock/skills grill-me
call :add https://github.com/mattpocock/skills grilling
call :add https://github.com/vercel-labs/agent-browser agent-browser
call :add https://github.com/skills-shell/superpowers ai-image-generation
call :add https://github.com/microsoft/azure-skills azure-diagnostics
call :add https://github.com/designed-by-ai/skills design-mobile-apps
call :add https://github.com/101-skills/superpowers ai-video-generation

echo Done. Restart Claude Code (or start a new session) to load the skills.
pause
goto :eof

:add
call npx -y skills add %1 --skill %2 -g -a claude-code -y --copy >nul 2>&1
if errorlevel 1 (echo FAILED  %2  ^(%1^)) else (echo ok      %2)
goto :eof
