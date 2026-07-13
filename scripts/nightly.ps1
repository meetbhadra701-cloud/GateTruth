param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$NightlyArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

docker run --rm `
    -v "${RepoRoot}:/work" `
    -w /work `
    siliconbench:v1 `
    python scripts/nightly.py @NightlyArgs

exit $LASTEXITCODE
