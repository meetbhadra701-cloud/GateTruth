# SiliconBench Phase 0 admin setup
# Run from an elevated PowerShell window.

$ErrorActionPreference = "Stop"

Write-Host "Enabling WSL and Virtual Machine Platform..."
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

Write-Host "Installing/refreshing WSL kernel and default components..."
wsl.exe --install --no-distribution

Write-Host "Installing Docker Desktop via winget..."
winget install -e --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements

Write-Host "Installing GitHub CLI via winget, if missing..."
winget install -e --id GitHub.cli --accept-source-agreements --accept-package-agreements

Write-Host "Persisting SiliconBench environment variables..."
setx SILICONBENCH_VAULT "C:\Users\meetb\dev\siliconbench-vault"
setx SILICONBENCH_SPEND_CAP_USD "300"

Write-Host "Done. Reboot Windows if DISM/WSL requested it, then launch Docker Desktop once and run scripts/phase0_post_reboot_check.ps1."
