param(
    [Parameter(Mandatory = $true)]
    [string]$RoundUrl,

    [string]$BackendUrl = "http://localhost:8000",

    [int]$Limit = 10,

    [switch]$IncludePgnText
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

$apiBase = $BackendUrl.TrimEnd("/")
$body = @{
    round_url = $RoundUrl.Trim()
    limit = $Limit
    include_pgn_text = $IncludePgnText.IsPresent
}

Write-Host ""
Write-Host "LaboraTobi Broadcast preview"
Write-Host "Backend: $apiBase"
Write-Host "Round URL: $($body.round_url)"
Write-Host ""

$preview = Invoke-LaboraTobiJson `
    -Method POST `
    -Uri "$apiBase/imports/broadcast/preview" `
    -Body $body

Write-Host "Tournament: $($preview.tournament_name)"
Write-Host "Round:      $($preview.round_name)"
Write-Host "Round id:   $($preview.round_id)"
Write-Host "Games:      $($preview.games_found) found, $($preview.games_previewed) previewed"
Write-Host "Quality:    score $($preview.quality.quality_score), confidence $($preview.quality.confidence), serious=$($preview.quality.is_serious_gm_broadcast)"
if (@($preview.quality.blocking_reasons).Count -gt 0) {
    Write-Host "Blocking reasons:"
    $preview.quality.blocking_reasons | ForEach-Object { Write-Host "  - $_" }
}
Write-Host ""

@($preview.games) | ForEach-Object {
    [pscustomobject]@{
        external_id = $_.external_id
        white = $_.white_player
        black = $_.black_player
        result = $_.result
        white_elo = $_.white_elo
        black_elo = $_.black_elo
    }
} | Format-Table -AutoSize
