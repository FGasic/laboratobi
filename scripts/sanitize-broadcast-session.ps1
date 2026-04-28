param(
    [string]$ApiBase = "http://localhost:8000",
    [int]$SwingThresholdCp = 100,
    [int]$MaxMoments = 3,
    [int]$MinSpacingPlies = 8,
    [int]$MinRemainingPlies = 4
)

$ErrorActionPreference = "Stop"

$body = @{
    swing_threshold_cp = $SwingThresholdCp
    max_moments = $MaxMoments
    min_spacing_plies = $MinSpacingPlies
    min_remaining_plies = $MinRemainingPlies
} | ConvertTo-Json

Invoke-RestMethod `
    -Method POST `
    -Uri "$ApiBase/analysis/sanitize-broadcast-session" `
    -ContentType "application/json" `
    -Body $body |
    ConvertTo-Json -Depth 12
