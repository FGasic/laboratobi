param(
    [Parameter(Mandatory = $true)]
    [string]$RoundId,

    [string[]]$ExternalIds = @(),

    [string]$BackendUrl = "http://localhost:8000",

    [int]$PreviewLimit = 20,

    [int]$Depth = 0,

    [int]$SwingThresholdCp = 100,

    [int]$MaxMoments = 3,

    [int]$MinSpacingPlies = 8,

    [int]$MinRemainingPlies = 4,

    [switch]$AllowLowQuality
)

$ErrorActionPreference = "Stop"

function Invoke-LaboraTobiJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [object]$Body = $null
    )

    $options = @{
        Method = $Method
        Uri = $Uri
        Headers = @{
            "accept" = "application/json"
        }
        TimeoutSec = 600
    }

    if ($null -ne $Body) {
        $options["ContentType"] = "application/json"
        $options["Body"] = ($Body | ConvertTo-Json -Depth 8)
    }

    try {
        Invoke-RestMethod @options
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            throw
        }

        $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
        $detail = $reader.ReadToEnd()
        throw "HTTP $([int]$response.StatusCode) from $Uri`n$detail"
    }
}

function Get-GameTrace {
    param(
        [Parameter(Mandatory = $true)]
        [int]$GameId,

        [Parameter(Mandatory = $true)]
        [string]$ApiBase
    )

    $game = Invoke-LaboraTobiJson -Method GET -Uri "$ApiBase/games/$GameId"
    $moments = Invoke-LaboraTobiJson -Method GET -Uri "$ApiBase/games/$GameId/critical-moments"

    [pscustomobject]@{
        external_id = $game.external_id
        game_id = $game.id
        white = $game.white_player
        black = $game.black_player
        result = $game.result
        critical_moments = @($moments).Count
    }
}

$apiBase = $BackendUrl.TrimEnd("/")
$normalizedRoundId = $RoundId.Trim()
if ($normalizedRoundId -notmatch "^[A-Za-z0-9]{8}$") {
    throw "RoundId must be an 8-character Lichess Broadcast round id."
}

$normalizedExternalIds = @(
    $ExternalIds |
        ForEach-Object { $_ -split "," } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ } |
        Select-Object -Unique
)

Write-Host ""
Write-Host "LaboraTobi daily Broadcast load"
Write-Host "Backend: $apiBase"
Write-Host "Round:   $normalizedRoundId"
Write-Host ""

$previewBody = @{
    round_id = $normalizedRoundId
    limit = $PreviewLimit
    include_pgn_text = $false
}
$preview = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/preview" `
    -Body $previewBody

Write-Host "Preview"
Write-Host "Tournament: $($preview.tournament_name)"
Write-Host "Round:      $($preview.round_name)"
Write-Host "Games:      $($preview.games_found) found, $($preview.games_previewed) previewed"
Write-Host "Quality:    score $($preview.quality.quality_score), confidence $($preview.quality.confidence), serious=$($preview.quality.is_serious_gm_broadcast)"
if (@($preview.quality.blocking_reasons).Count -gt 0) {
    Write-Host "Blocking reasons:"
    $preview.quality.blocking_reasons | ForEach-Object { Write-Host "  - $_" }
}
Write-Host ""

$previewRows = @($preview.games) | ForEach-Object {
    [pscustomobject]@{
        external_id = $_.external_id
        white = $_.white_player
        black = $_.black_player
        white_elo = $_.white_elo
        black_elo = $_.black_elo
    }
}
$previewRows | Format-Table -AutoSize

if ($normalizedExternalIds.Count -eq 0) {
    Write-Host ""
    Write-Host "Preview only. Pick exactly 3 external_ids, then run:"
    Write-Host "powershell -ExecutionPolicy Bypass -File .\scripts\load-daily-broadcast.ps1 -RoundId $normalizedRoundId -ExternalIds id1,id2,id3"
    return
}

if ($normalizedExternalIds.Count -ne 3) {
    throw "Daily load requires exactly 3 unique external_ids. Received $($normalizedExternalIds.Count)."
}

$previewExternalIds = @($preview.games | ForEach-Object { $_.external_id })
$missingExternalIds = @($normalizedExternalIds | Where-Object { $_ -notin $previewExternalIds })
if ($missingExternalIds.Count -gt 0) {
    throw "These external_ids were not found in the previewed round: $($missingExternalIds -join ', ')"
}

Write-Host ""
Write-Host "Importing exactly 3 games and generating critical moments..."
Write-Host ($normalizedExternalIds -join ", ")
Write-Host ""

$importBody = @{
    round_id = $normalizedRoundId
    external_ids = $normalizedExternalIds
    allow_low_quality = $AllowLowQuality.IsPresent
    generate_critical_moments = $true
    swing_threshold_cp = $SwingThresholdCp
    max_moments = $MaxMoments
    min_spacing_plies = $MinSpacingPlies
    min_remaining_plies = $MinRemainingPlies
}
if ($Depth -gt 0) {
    $importBody["depth"] = $Depth
}

$import = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/import" `
    -Body $importBody

Write-Host "Import result"
Write-Host "Requested: $($import.requested_count)"
Write-Host "Imported:  $($import.imported_count)"
Write-Host "Skipped:   $($import.skipped_count)"
Write-Host "Analyzed:  $($import.analyzed_count)"
Write-Host "Moments:   $($import.total_generated_moments)"
Write-Host ""

$traceRows = @()
foreach ($externalId in $normalizedExternalIds) {
    $importedGame = @($import.imported_games) | Where-Object { $_.external_id -eq $externalId } | Select-Object -First 1
    if ($null -ne $importedGame) {
        $traceRows += [pscustomobject]@{
            external_id = $externalId
            game_id = $importedGame.id
            status = "imported"
            white = $importedGame.white_player
            black = $importedGame.black_player
            critical_moments = $importedGame.generated_moments_count
            analysis_error = $importedGame.analysis_error
        }
        continue
    }

    $skippedGame = @($import.skipped_games) | Where-Object { $_.external_id -eq $externalId } | Select-Object -First 1
    if ($null -ne $skippedGame -and $null -ne $skippedGame.existing_game_id) {
        $trace = Get-GameTrace -GameId $skippedGame.existing_game_id -ApiBase $apiBase
        $traceRows += [pscustomobject]@{
            external_id = $externalId
            game_id = $trace.game_id
            status = $skippedGame.reason
            white = $trace.white
            black = $trace.black
            critical_moments = $trace.critical_moments
            analysis_error = $null
        }
        continue
    }

    $traceRows += [pscustomobject]@{
        external_id = $externalId
        game_id = $null
        status = "not_ready"
        white = $null
        black = $null
        critical_moments = 0
        analysis_error = "No imported or existing game found."
    }
}

Write-Host "Trace"
$traceRows | Format-Table -AutoSize

$failedRows = @($traceRows | Where-Object { $null -eq $_.game_id -or $_.critical_moments -lt 1 -or $_.analysis_error })
if ($failedRows.Count -gt 0) {
    throw "Daily load did not leave all 3 games ready with active critical moments."
}

$session = Invoke-LaboraTobiJson -Method GET -Uri "$apiBase/games/broadcast/session"
$sessionRows = @($session.games) | ForEach-Object {
    [pscustomobject]@{
        external_id = $_.external_id
        game_id = $_.id
        white = $_.white_player
        black = $_.black_player
        critical_moments = $_.critical_moments_count
    }
}

Write-Host ""
Write-Host "Current /study session"
$sessionRows | Format-Table -AutoSize

$readyGameIds = @($traceRows | ForEach-Object { [int]$_.game_id })
$sessionGameIds = @($sessionRows | ForEach-Object { [int]$_.game_id })
$missingFromSession = @($readyGameIds | Where-Object { $_ -notin $sessionGameIds })
if ($missingFromSession.Count -gt 0) {
    throw "/study is not prioritizing all 3 selected games. Missing game_id(s): $($missingFromSession -join ', ')"
}

Write-Host ""
Write-Host "OK: the 3 selected games are imported/existing, have active critical moments, and are in /study."
