param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Require-File($Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Missing required file: $Path"
  }
}

function Require-Text($Path, $Pattern) {
  $text = Get-Content -Raw -LiteralPath $Path
  if ($text -notmatch $Pattern) {
    throw "Missing pattern '$Pattern' in $Path"
  }
}

$dockerfile = Join-Path $Root "flows\Dockerfile"
$versions = Join-Path $Root "flows\VERSIONS.md"
$digest = Join-Path $Root "flows\record_digest.sh"

Require-File $dockerfile
Require-File $versions
Require-File $digest
Require-File (Join-Path $Root ".dockerignore")

Require-Text $dockerfile "FROM --platform=linux/amd64 debian:bookworm-slim AS base"
Require-Text $dockerfile "OSS_CAD_SUITE_TAG=2026-07-08"
Require-Text $dockerfile "OSS_CAD_SUITE_ASSET_DATE=20260708"
Require-Text $dockerfile "5b24af7c0fa639a8105e4b6e128cee24dcfc1316e1bbd7b8a9d06b4dac10313e"
Require-Text $dockerfile "IVERILOG_REF=v12_0"
Require-Text $dockerfile "VOLARE_SKY130_TAG=sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392"
Require-Text $dockerfile "VOLARE_SKY130_HD_SHA256=d4081b3c0fbfa2afe31dba789c03157ad137ea08b11910e2c8b3ec81b2a61bf6"
Require-Text $dockerfile "/opt/iverilog/bin:/opt/oss-cad-suite/bin"
Require-Text $dockerfile "ln -sf /usr/bin/python3.11 /usr/local/bin/python"
Require-Text $dockerfile "python --version"
Require-Text $dockerfile "python3 --version"
Require-Text $dockerfile "opensta"
Require-Text $dockerfile "command -v iverilog"
Require-Text $dockerfile "sta -version"
Require-Text $dockerfile "yosys -V"
Require-Text $dockerfile "sby --help"
Require-Text $dockerfile "eqy --help"
Require-Text $dockerfile "ls /pdk/sky130hd/\*\.lib /pdk/sky130hd/\*\.lef"
Require-Text $versions "Debian bookworm ``opensta`` package"
Require-Text $versions "runtime aliases"
Require-Text $versions "Volare sky130 prebuilt PDK"

$bad = Select-String -LiteralPath $dockerfile,$versions -Pattern "REPLACE_WITH|OSS_CAD_SUITE_DATE|2025-10-14|SKY130_FD_SC_HD_COMMIT|skywater-pdk-libs-sky130_fd_sc_hd|OPEN_PDKS_REF|OPEN_PDKS_COMMIT|open_pdks" -ErrorAction SilentlyContinue
if ($bad) {
  throw "Found stale placeholder or obsolete pin text:`n$($bad | Out-String)"
}

Write-Output "SB-001 static scaffold check passed"
