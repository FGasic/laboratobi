param(
    [Parameter(Mandatory = $true)]
    [string]$RoundUrl,

    [string]$BackendUrl = "http://localhost:8000",

    [int]$Limit = 10,

    [int]$Depth = 0,

    [int]$SwingThresholdCp = 100,

    [int]$MaxMoments = 3,

    [int]$MinSpacingPlies = 8,

    [int]$MinRemainingPlies = 4,

    [switch]$AllowLowQuality,

    [switch]$SkipCriticalMoments
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
        TimeoutSec = 900
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

function Invoke-CriticalMomentGeneration {
    param(
        [Parameter(Mandatory = $true)]
        [int]$GameId,

        [Parameter(Mandatory = $true)]
        [string]$ApiBase
    )

    $body = @{
        game_id = $GameId
        swing_threshold_cp = $SwingThresholdCp
        max_moments = $MaxMoments
        min_spacing_plies = $MinSpacingPlies
        min_remaining_plies = $MinRemainingPlies
    }
    if ($Depth -gt 0) {
        $body["depth"] = $Depth
    }

    Invoke-LaboraTobiJson `
        -Method POST `
        -Uri "$ApiBase/analysis/generate-critical-moments" `
        -Body $body
}

$apiBase = $BackendUrl.TrimEnd("/")
$normalizedRoundUrl = $RoundUrl.Trim()
$generateCriticalMoments = -not $SkipCriticalMoments.IsPresent

Write-Host ""
Write-Host "LaboraTobi Broadcast import"
Write-Host "Backend: $apiBase"
Write-Host "Round URL: $normalizedRoundUrl"
Write-Host "Limit:   $Limit"
Write-Host "Analyze: $generateCriticalMoments"
Write-Host ""

$previewBody = @{
    round_url = $normalizedRoundUrl
    limit = $Limit
    include_pgn_text = $false
}
$preview = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/preview" `
    -Body $previewBody

Write-Host "Preview"
Write-Host "Tournament: $($preview.tournament_name)"
Write-Host "Round:      $($preview.round_name)"
Write-Host "Round id:   $($preview.round_id)"
Write-Host "Games:      $($preview.games_found) found, $($preview.games_previewed) selected by limit"
Write-Host "Quality:    score $($preview.quality.quality_score), confidence $($preview.quality.confidence), serious=$($preview.quality.is_serious_gm_broadcast)"
if (@($preview.quality.blocking_reasons).Count -gt 0) {
    Write-Host "Blocking reasons:"
    $preview.quality.blocking_reasons | ForEach-Object { Write-Host "  - $_" }
}
Write-Host ""

$importBody = @{
    round_url = $normalizedRoundUrl
    limit = $Limit
    include_pgn_text = $false
    allow_low_quality = $AllowLowQuality.IsPresent
    generate_critical_moments = $false
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
foreach ($game in @($import.imported_games)) {
    $momentsCount = $game.generated_moments_count
    $analysisError = $game.analysis_error

    if ($generateCriticalMoments -and $momentsCount -lt 1) {
        try {
            Write-Host "Generating critical moments for game_id=$($game.id)..."
            $analysis = Invoke-CriticalMomentGeneration `
                -GameId $game.id `
                -ApiBase $apiBase
            $momentsCount = $analysis.generated_count
        } catch {
            $analysisError = $_.Exception.Message
        }
    }

    $traceRows += [pscustomobject]@{
        game_id = $game.id
        external_id = $game.external_id
        status = "imported"
        white = $game.white_player
        black = $game.black_player
        critical_moments = $momentsCount
        analysis_error = $analysisError
    }
}

foreach ($skipped in @($import.skipped_games)) {
    $momentsCount = 0
    $analysisError = $null
    if ($null -ne $skipped.existing_game_id) {
        $moments = Invoke-LaboraTobiJson `
            -Method GET `
            -Uri "$apiBase/games/$($skipped.existing_game_id)/critical-moments"
        $momentsCount = @($moments).Count

        if ($generateCriticalMoments -and $momentsCount -lt 1) {
            try {
                Write-Host "Generating critical moments for existing game_id=$($skipped.existing_game_id)..."
                $analysis = Invoke-CriticalMomentGeneration `
                    -GameId $skipped.existing_game_id `
                    -ApiBase $apiBase
                $momentsCount = $analysis.generated_count
            } catch {
                $analysisError = $_.Exception.Message
            }
        }
    }

    $traceRows += [pscustomobject]@{
        game_id = $skipped.existing_game_id
        external_id = $skipped.external_id
        status = $skipped.reason
        white = $null
        black = $null
        critical_moments = $momentsCount
        analysis_error = $analysisError
    }
}

Write-Host "Trace"
$traceRows | Format-Table -AutoSize

$recent = Invoke-LaboraTobiJson -Method GET -Uri "$apiBase/games/broadcast/recent"
$session = Invoke-LaboraTobiJson -Method GET -Uri "$apiBase/games/broadcast/session"

Write-Host ""
Write-Host "Recent Broadcast games"
@($recent) | ForEach-Object {
    [pscustomobject]@{
        game_id = $_.id
        external_id = $_.external_id
        white = $_.white_player
        black = $_.black_player
        critical_moments = $_.critical_moments_count
    }
} | Format-Table -AutoSize

Write-Host ""
Write-Host "/study session"
@($session.games) | ForEach-Object {
    [pscustomobject]@{
        game_id = $_.id
        external_id = $_.external_id
        white = $_.white_player
        black = $_.black_player
        critical_moments = $_.critical_moments_count
    }
} | Format-Table -AutoSize

Write-Host ""
Write-Host "OK: Broadcast round processed from round_url."
