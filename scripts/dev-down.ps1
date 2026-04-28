$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    docker compose down --remove-orphans
} finally {
    Pop-Location
}
