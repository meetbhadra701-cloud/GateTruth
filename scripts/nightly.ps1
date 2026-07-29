param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$NightlyArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gatetruth-nightly-" + [guid]::NewGuid())
$SourceRoot = Join-Path $RunRoot "source"
$Archive = Join-Path $RunRoot "source.tar"
$OutputRoot = Join-Path $RepoRoot "build\nightly-output"
$SiteOutputRoot = Join-Path $RepoRoot "build\nightly-site"

New-Item -ItemType Directory -Force -Path $SourceRoot, $OutputRoot, $SiteOutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $SourceRoot "results\nightly") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $SourceRoot "site\build") | Out-Null

try {
    git -C $RepoRoot archive --format=tar HEAD -o $Archive
    if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
    tar -xf $Archive -C $SourceRoot
    if ($LASTEXITCODE -ne 0) { throw "source extraction failed" }

    docker run --rm `
        --network none `
        --cap-drop=ALL `
        --security-opt no-new-privileges `
        --memory=4g `
        --pids-limit=512 `
        --cpus=2 `
        --mount "type=bind,source=${SourceRoot},target=/work,readonly" `
        --mount "type=bind,source=${OutputRoot},target=/work/results/nightly" `
        --mount "type=bind,source=${SiteOutputRoot},target=/work/site/build" `
        --workdir /work `
        gatetruth:v1 `
        python scripts/nightly.py @NightlyArgs
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $RunRoot -Recurse -Force -ErrorAction SilentlyContinue
}
