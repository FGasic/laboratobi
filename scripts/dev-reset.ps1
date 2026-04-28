$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectName = (Split-Path -Leaf $repoRoot).ToLowerInvariant()
$frontendNextVolume = "${projectName}_frontend_next"

Push-Location $repoRoot
try {
    docker compose down --remove-orphans
    docker volume rm $frontendNextVolume 2>$null | Out-Null
    docker compose up -d --build --remove-orphans
    docker compose ps
} finally {
    Pop-Location
}
