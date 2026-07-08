# SiliconBench Phase 0 post-reboot check
# Run in a fresh non-admin PowerShell after rebooting and launching Docker Desktop once.

$ErrorActionPreference = "Stop"

& "C:\Program Files\GitHub CLI\gh.exe" --version
& "C:\Program Files\GitHub CLI\gh.exe" auth status

docker --version
docker run --rm alpine uname -m

Write-Host "If gh auth status says not logged in, run: gh auth login"
Write-Host "After auth, flip repo private before first push:"
Write-Host "gh repo edit meetbhadra701-cloud/SiliconBench --visibility private --accept-visibility-change-consequences"
