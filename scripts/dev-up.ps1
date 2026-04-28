$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    docker compose up -d --build --remove-orphans
    docker compose ps

    Write-Host ""
    Write-Host "LaboraTobi local:"
    Write-Host "  Frontend: http://localhost:3000"
    Write-Host "  Backend:  http://localhost:8000"
    Write-Host "  Docs:     http://localhost:8000/docs"
    Write-Host ""
    Write-Host "Logs en vivo: docker compose logs -f frontend backend"
} finally {
    Pop-Location
}
