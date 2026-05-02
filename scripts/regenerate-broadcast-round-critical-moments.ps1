param(
    [Parameter(Mandatory = $true)]
    [string]$RoundUrl,

    [string]$BackendUrl = "http://localhost:8000",

    [int]$Limit = 10,

    [string[]]$ExternalIds = @(),

    [int]$Depth = 20,

    [int]$ReviewDepth = 25,

    [int]$SwingThresholdCp = 100,

    [int]$MaxMoments = 3,

    [int]$MinSpacingPlies = 8,

    [int]$MinRemainingPlies = 4,

    [switch]$AllowLowQuality
)

$ErrorActionPreference = "Stop"
$maxAbsInitialEvalCp = 80

function Invoke-LaboraTobiJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "DELETE")]
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
        TimeoutSec = 1800
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

function ConvertTo-LaboraTobiArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }

    return @($Value)
}

function Invoke-CriticalMomentGeneration {
    param(
        [Parameter(Mandatory = $true)]
        [int]$GameId,

        [Parameter(Mandatory = $true)]
        [string]$ApiBase
    )

    Invoke-LaboraTobiJson `
        -Method POST `
        -Uri "$ApiBase/analysis/generate-critical-moments" `
        -Body @{
            game_id = $GameId
            depth = $Depth
            swing_threshold_cp = $SwingThresholdCp
            max_moments = $MaxMoments
            min_spacing_plies = $MinSpacingPlies
            min_remaining_plies = $MinRemainingPlies
        }
}

function Get-ReviewValidation {
    param(
        [Parameter(Mandatory = $true)]
        [int]$GameId,

        [Parameter(Mandatory = $true)]
        [object[]]$Moments,

        [Parameter(Mandatory = $true)]
        [string]$ApiBase
    )

    if (@($Moments).Count -eq 0) {
        return [pscustomobject]@{
            reviewed_count = 0
            missing_review_count = 0
            out_of_range_count = 0
        }
    }

    $plyIndexes = @($Moments | ForEach-Object { [int]$_.ply_index })
    $reviews = Invoke-LaboraTobiJson `
        -Method POST `
        -Uri "$ApiBase/analysis/review-critical-moments" `
        -Body @{
            game_id = $GameId
            ply_indexes = $plyIndexes
            depth = $ReviewDepth
        }

    $reviewedMoments = @(ConvertTo-LaboraTobiArray $reviews.moments)
    $outOfRange = @(
        $reviewedMoments | Where-Object {
            $null -ne $_.engine_line_eval_cp -and
            [Math]::Abs([int]$_.engine_line_eval_cp) -gt $maxAbsInitialEvalCp
        }
    )

    [pscustomobject]@{
        reviewed_count = $reviewedMoments.Count
        missing_review_count = @($Moments).Count - $reviewedMoments.Count
        out_of_range_count = $outOfRange.Count
    }
}

$apiBase = $BackendUrl.TrimEnd("/")
$normalizedRoundUrl = $RoundUrl.Trim()
$normalizedExternalIds = @(
    $ExternalIds |
        ForEach-Object { $_ -split "," } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)

Write-Host ""
Write-Host "LaboraTobi critical moment regeneration"
Write-Host "Backend: $apiBase"
Write-Host "Round URL: $normalizedRoundUrl"
Write-Host "Limit: $Limit"
if ($normalizedExternalIds.Count -gt 0) {
    Write-Host "External IDs: $($normalizedExternalIds -join ', ')"
}
Write-Host "Generation depth: $Depth"
Write-Host "Review depth: $ReviewDepth"
Write-Host "Initial eval filter: inclusive +/-$maxAbsInitialEvalCp cp"
Write-Host ""

$preview = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/preview" `
    -Body @{
        round_url = $normalizedRoundUrl
        limit = $Limit
        include_pgn_text = $false
    }

Write-Host "Preview"
Write-Host "Tournament: $($preview.tournament_name)"
Write-Host "Round: $($preview.round_name)"
Write-Host "Round id: $($preview.round_id)"
Write-Host "Games: $($preview.games_found) found, $($preview.games_previewed) selected"
Write-Host ""

$importBody = @{
    round_url = $normalizedRoundUrl
    limit = $Limit
    include_pgn_text = $false
    allow_low_quality = $AllowLowQuality.IsPresent
    generate_critical_moments = $false
}
if ($normalizedExternalIds.Count -gt 0) {
    $importBody["external_ids"] = $normalizedExternalIds
}

$import = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/import" `
    -Body $importBody

$affectedRows = @()
foreach ($game in @($import.imported_games)) {
    $affectedRows += [pscustomobject]@{
        game_id = [int]$game.id
        external_id = $game.external_id
        source = "imported"
    }
}

foreach ($skipped in @($import.skipped_games)) {
    if ($null -eq $skipped.existing_game_id) {
        continue
    }

    $affectedRows += [pscustomobject]@{
        game_id = [int]$skipped.existing_game_id
        external_id = $skipped.external_id
        source = $skipped.reason
    }
}

$affectedGameIds = @(
    $affectedRows |
        Where-Object { $null -ne $_.game_id } |
        Select-Object -ExpandProperty game_id -Unique
)

if ($affectedGameIds.Count -eq 0) {
    throw "No imported or existing games were found for this round."
}

$traceRows = @()
foreach ($gameId in $affectedGameIds) {
    Write-Host "Regenerating critical moments for game_id=$gameId..."

    $activeMomentsBefore = @(ConvertTo-LaboraTobiArray (
        Invoke-LaboraTobiJson `
            -Method GET `
            -Uri "$apiBase/games/$gameId/critical-moments"
    ))

    foreach ($moment in $activeMomentsBefore) {
        Invoke-LaboraTobiJson `
            -Method DELETE `
            -Uri "$apiBase/games/$gameId/critical-moments/$($moment.id)" |
            Out-Null
    }

    $generation = Invoke-CriticalMomentGeneration -GameId $gameId -ApiBase $apiBase
    $activeMomentsAfter = @(ConvertTo-LaboraTobiArray (
        Invoke-LaboraTobiJson `
            -Method GET `
            -Uri "$apiBase/games/$gameId/critical-moments"
    ))
    $validation = Get-ReviewValidation `
        -GameId $gameId `
        -Moments $activeMomentsAfter `
        -ApiBase $apiBase

    if ($validation.missing_review_count -gt 0 -or $validation.out_of_range_count -gt 0) {
        Write-Warning (
            "Deactivating generated moments for game_id=${gameId}: " +
            "missing_review_count=$($validation.missing_review_count), " +
            "out_of_range_count=$($validation.out_of_range_count)."
        )
        foreach ($moment in $activeMomentsAfter) {
            Invoke-LaboraTobiJson `
                -Method DELETE `
                -Uri "$apiBase/games/$gameId/critical-moments/$($moment.id)" |
                Out-Null
        }

        $activeMomentsAfter = @()
        $validation = [pscustomobject]@{
            reviewed_count = 0
            missing_review_count = 0
            out_of_range_count = 0
        }
    }

    $traceRows += [pscustomobject]@{
        game_id = $gameId
        active_before = $activeMomentsBefore.Count
        deactivated = $activeMomentsBefore.Count
        generated = $generation.generated_count
        active_after = $activeMomentsAfter.Count
        reviewed_at_review_depth = $validation.reviewed_count
        out_of_range_at_review_depth = $validation.out_of_range_count
    }
}

$session = Invoke-LaboraTobiJson -Method GET -Uri "$apiBase/games/broadcast/session"

Write-Host ""
Write-Host "Regeneration trace"
$traceRows | Format-Table -AutoSize

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
Write-Host "OK: critical moments regenerated with the backend initial eval filter."
