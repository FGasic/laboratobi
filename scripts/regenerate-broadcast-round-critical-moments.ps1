param(
    [Parameter(Mandatory = $true)]
    [string]$RoundUrl,

    [string]$BackendUrl = "http://localhost:8000",

    [int]$Limit = 20,

    [int]$LimitStep = 20,

    [int]$RequiredStudyGames = 3,

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
        [AllowEmptyCollection()]
        [object[]]$Moments,

        [Parameter(Mandatory = $true)]
        [string]$ApiBase
    )

    if (@($Moments).Count -eq 0) {
        return [pscustomobject]@{
            reviewed_count = 0
            missing_review_count = 0
            invalid_review_count = 0
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
    $invalidReviews = @(
        $reviewedMoments | Where-Object {
            $principalVariation = @(ConvertTo-LaboraTobiArray $_.engine_principal_variation)
            -not $_.engine_best_move -or
            $principalVariation.Count -eq 0 -or
            $null -eq $_.engine_line_eval_cp -or
            [Math]::Abs([int]$_.engine_line_eval_cp) -gt $maxAbsInitialEvalCp -or
            ($null -eq $_.played_move_eval_cp -and $null -eq $_.played_move_mate) -or
            -not $_.engine_name -or
            $null -eq $_.depth_used -or
            [int]$_.depth_used -lt $ReviewDepth
        }
    )

    [pscustomobject]@{
        reviewed_count = $reviewedMoments.Count
        missing_review_count = @($Moments).Count - $reviewedMoments.Count
        invalid_review_count = $invalidReviews.Count
        out_of_range_count = $outOfRange.Count
    }
}

function Invoke-BroadcastPreview {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ApiBase,

        [Parameter(Mandatory = $true)]
        [string]$RoundUrl,

        [Parameter(Mandatory = $true)]
        [int]$PreviewLimit
    )

    Invoke-LaboraTobiJson `
        -Method POST `
        -Uri "$ApiBase/imports/broadcast/preview" `
        -Body @{
            round_url = $RoundUrl
            limit = $PreviewLimit
            include_pgn_text = $false
        }
}

function Invoke-BroadcastImport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ApiBase,

        [Parameter(Mandatory = $true)]
        [string]$RoundUrl,

        [Parameter(Mandatory = $true)]
        [int]$ImportLimit,

        [string[]]$ExternalIds = @()
    )

    $importBody = @{
        round_url = $RoundUrl
        limit = $ImportLimit
        include_pgn_text = $false
        allow_low_quality = $AllowLowQuality.IsPresent
        generate_critical_moments = $false
    }
    if ($ExternalIds.Count -gt 0) {
        $importBody["external_ids"] = $ExternalIds
    }

    Invoke-LaboraTobiJson `
        -Method POST `
        -Uri "$ApiBase/imports/broadcast/import" `
        -Body $importBody
}

function Get-AffectedGameIds {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Import
    )

    $affectedRows = @()
    foreach ($game in @($Import.imported_games)) {
        $affectedRows += [pscustomobject]@{
            game_id = [int]$game.id
            external_id = $game.external_id
            source = "imported"
        }
    }

    foreach ($skipped in @($Import.skipped_games)) {
        if ($null -eq $skipped.existing_game_id) {
            continue
        }

        $affectedRows += [pscustomobject]@{
            game_id = [int]$skipped.existing_game_id
            external_id = $skipped.external_id
            source = $skipped.reason
        }
    }

    @(
        $affectedRows |
            Where-Object { $null -ne $_.game_id } |
            Select-Object -ExpandProperty game_id -Unique
    )
}

function Get-StudySessionStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ApiBase,

        [Parameter(Mandatory = $true)]
        [int]$RequiredGames
    )

    try {
        $session = Invoke-LaboraTobiJson -Method GET -Uri "$ApiBase/games/broadcast/session"
        $games = @(ConvertTo-LaboraTobiArray $session.games)
        $allHaveOneMoment = @(
            $games | Where-Object { [int]$_.critical_moments_count -eq 1 }
        ).Count -eq $games.Count

        return [pscustomobject]@{
            ready = ($games.Count -eq $RequiredGames -and $allHaveOneMoment)
            count = $games.Count
            session = $session
            error = $null
        }
    } catch {
        return [pscustomobject]@{
            ready = $false
            count = 0
            session = $null
            error = $_.Exception.Message
        }
    }
}

if ($Limit -lt 1) {
    throw "Limit must be at least 1."
}
if ($LimitStep -lt 1) {
    throw "LimitStep must be at least 1."
}
if ($RequiredStudyGames -ne 3) {
    throw "RequiredStudyGames must be 3 for /study."
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
Write-Host "Initial limit: $Limit"
Write-Host "Limit step: $LimitStep"
Write-Host "Required /study games: $RequiredStudyGames"
if ($normalizedExternalIds.Count -gt 0) {
    Write-Host "External IDs: $($normalizedExternalIds -join ', ')"
}
Write-Host "Generation depth: $Depth"
Write-Host "Review depth: $ReviewDepth"
Write-Host "Initial eval filter: inclusive +/-$maxAbsInitialEvalCp cp"
Write-Host ""

$preview = Invoke-BroadcastPreview `
    -ApiBase $apiBase `
    -RoundUrl $normalizedRoundUrl `
    -PreviewLimit $Limit

Write-Host "Preview"
Write-Host "Tournament: $($preview.tournament_name)"
Write-Host "Round: $($preview.round_name)"
Write-Host "Round id: $($preview.round_id)"
Write-Host "Games: $($preview.games_found) found"
Write-Host ""

$roundGameLimit = [int]$preview.games_found
if ($normalizedExternalIds.Count -gt 0) {
    $roundGameLimit = $normalizedExternalIds.Count
}
$currentLimit = [Math]::Min($Limit, $roundGameLimit)
$processedGameIds = @{}
$traceRows = @()
$sessionStatus = $null

while ($true) {
    Write-Host "Import/regeneration pass: first $currentLimit game(s)"

    $import = Invoke-BroadcastImport `
        -ApiBase $apiBase `
        -RoundUrl $normalizedRoundUrl `
        -ImportLimit $currentLimit `
        -ExternalIds $normalizedExternalIds

    $affectedGameIds = @(Get-AffectedGameIds -Import $import)
    $newGameIds = @(
        $affectedGameIds | Where-Object { -not $processedGameIds.ContainsKey([string]$_) }
    )

    if ($affectedGameIds.Count -eq 0) {
        throw "No imported or existing games were found for this round."
    }

    foreach ($gameId in $newGameIds) {
        $processedGameIds[[string]$gameId] = $true
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

        if (
            $validation.missing_review_count -gt 0 -or
            $validation.invalid_review_count -gt 0 -or
            $validation.out_of_range_count -gt 0
        ) {
            Write-Warning (
                "Deactivating generated moments for game_id=${gameId}: " +
                "missing_review_count=$($validation.missing_review_count), " +
                "invalid_review_count=$($validation.invalid_review_count), " +
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
                invalid_review_count = 0
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
            invalid_at_review_depth = $validation.invalid_review_count
            out_of_range_at_review_depth = $validation.out_of_range_count
        }

        $sessionStatus = Get-StudySessionStatus `
            -ApiBase $apiBase `
            -RequiredGames $RequiredStudyGames
        if ($sessionStatus.ready) {
            break
        }
    }

    if ($sessionStatus -and $sessionStatus.ready) {
        break
    }

    $sessionStatus = Get-StudySessionStatus `
        -ApiBase $apiBase `
        -RequiredGames $RequiredStudyGames
    if ($sessionStatus.ready) {
        break
    }

    if ($normalizedExternalIds.Count -gt 0 -or $currentLimit -ge $roundGameLimit) {
        break
    }

    $nextLimit = [Math]::Min($currentLimit + $LimitStep, $roundGameLimit)
    Write-Host (
        "/study has $($sessionStatus.count) valid game(s); " +
        "expanding analysis limit to $nextLimit."
    )
    $currentLimit = $nextLimit
}

if (-not $sessionStatus.ready) {
    $message = (
        "Expected $RequiredStudyGames valid /study games, got " +
        "$($sessionStatus.count) after processing $($processedGameIds.Count) " +
        "game(s) out of $roundGameLimit."
    )
    if ($sessionStatus.error) {
        $message += " Last session error: $($sessionStatus.error)"
    }
    throw $message
}

$session = $sessionStatus.session

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
Write-Host "OK: critical moments regenerated and /study has exactly $RequiredStudyGames ranked games."
