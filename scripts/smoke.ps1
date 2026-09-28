param(
    [string]$ApiUrl = "http://localhost:5000",
    [string]$MlUrl = "http://localhost:8000",
    [switch]$SkipInitialCleanup
)

$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    Write-Host "OK: $Message"
}

function Invoke-JsonPost([string]$Uri, $Body) {
    Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 20)
}

function Is-Dangerous($Prediction) {
    @($Prediction.decisions.psobject.Properties.Value | Where-Object { $_ -eq $true }).Count -gt 0
}

for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $health = Invoke-RestMethod "$ApiUrl/health"
        $mlHealth = Invoke-RestMethod "$MlUrl/health"
        if ($health.status -eq "ok" -and $mlHealth.status -eq "ok") { break }
    } catch {
        if ($attempt -eq 60) { throw "Services did not start within 120 seconds" }
        Start-Sleep -Seconds 2
    }
}

$docs = Invoke-WebRequest "$MlUrl/docs" -UseBasicParsing
Assert-True ($docs.StatusCode -eq 200 -and $docs.Content -match "Swagger UI") "FastAPI documentation is available"

# Begin from a known state. The optional switch is useful after a read-only audit
# has already confirmed that no demonstration rows exist.
if (-not $SkipInitialCleanup) {
    Invoke-RestMethod -Method Delete -Uri "$ApiUrl/api/model-demo/results" | Out-Null
}
$baselineObjects = Invoke-RestMethod "$ApiUrl/api/objects"
$baselineAlerts = Invoke-RestMethod "$ApiUrl/api/alerts"
$baselineRequests = Invoke-RestMethod "$ApiUrl/api/requests"
$baselineSms = Invoke-RestMethod "$ApiUrl/api/sms"
$baselineObjectIds = @($baselineObjects.id | Sort-Object)
$baselineAlertIds = @($baselineAlerts.id | Sort-Object)
Write-Host "Baseline counts: objects=$($baselineObjects.Count), alerts=$($baselineAlerts.Count), requests=$($baselineRequests.Count), sms=$($baselineSms.Count)"

$levels = @($baselineAlerts.level | Sort-Object -Unique)
Assert-True ($baselineObjects.Count -ge 4) "baseline objects are loaded"
Assert-True (@($levels | Where-Object { $_ -in @("green", "yellow", "red", "black") }).Count -eq 4) "GREEN, YELLOW, RED and BLACK are available"

$main = Invoke-RestMethod "$ApiUrl/api/alerts/11111111-1111-1111-1111-111111111111"
$history = @($main.history.toLevel)
Assert-True (($history -join ",") -eq "green,yellow,red,black,red") "escalation and de-escalation are deterministic"
Assert-True (@($main.channels | Where-Object { $null -eq $_.picketSortKey }).Count -ge 1) "channel without a picket is preserved"
Assert-True (@($main.channels | Where-Object { $_.deviceAgeYears -gt 0 -and $_.ageSource }).Count -eq $main.channels.Count) "device age and source are present"
Assert-True (@($baselineSms | Where-Object { $_.alertLevel -eq "black" -and $_.recipientId -like "response-*" }).Count -ge 1) "response team receives BLACK"

$summaries = Invoke-RestMethod "$ApiUrl/api/model-demo/scenarios"
Assert-True ($summaries.Count -eq 24) "exactly 24 held-out scenarios are exposed"
Assert-True (@($summaries | Where-Object { $_.psobject.Properties.Name -contains "features" -or $_.psobject.Properties.Name -contains "probability" }).Count -eq 0) "browser summaries contain no feature vectors or prepared probabilities"

$safe = $null
$dangerous = $null
foreach ($scenario in $summaries) {
    $calculation = Invoke-JsonPost "$ApiUrl/api/model-demo/predict" @{ scenarioId = $scenario.id }
    if (Is-Dangerous $calculation.prediction) { if ($null -eq $dangerous) { $dangerous = $calculation } }
    else { if ($null -eq $safe) { $safe = $calculation } }
    if ($null -ne $safe -and $null -ne $dangerous) { break }
}
Assert-True ($null -ne $safe) "held-out sequence contains a below-threshold result"
Assert-True ($null -ne $dangerous) "held-out sequence contains a threshold-exceeding result"

$catalogPath = Join-Path $PSScriptRoot "../services/api/FireRisk.Api/Data/model-demo-scenarios.json"
$catalog = Get-Content -Raw $catalogPath | ConvertFrom-Json
$fixture = $catalog.scenarios | Where-Object { $_.id -eq $dangerous.scenario.id } | Select-Object -First 1
$direct = Invoke-JsonPost "$MlUrl/ml/predict" @{ features = $fixture.features; topK = 5 }
foreach ($field in @("p_now", "p_6h", "p_12h", "p_24h")) {
    Assert-True ([Math]::Abs([double]$direct.$field - [double]$dangerous.prediction.$field) -lt 0.0000000001) "demo API matches direct inference for $field"
}

$safeRejected = $false
try {
    Invoke-JsonPost "$ApiUrl/api/model-demo/publish" @{ calculationId = $safe.calculationId } | Out-Null
} catch {
    $safeRejected = [int]$_.Exception.Response.StatusCode -eq 409
}
Assert-True $safeRejected "below-threshold result cannot be published"

$published = Invoke-JsonPost "$ApiUrl/api/model-demo/publish" @{ calculationId = $dangerous.calculationId }
$replayed = Invoke-JsonPost "$ApiUrl/api/model-demo/publish" @{ calculationId = $dangerous.calculationId }
Assert-True ($published.alertId -eq $replayed.alertId) "publication replay returns the same alert"

$demoAlert = Invoke-RestMethod "$ApiUrl/api/alerts/$($published.alertId)"
Assert-True ($demoAlert.isDemo -eq $true) "published warning is visible in the existing alert API with a demo marker"

$request = Invoke-JsonPost "$ApiUrl/api/alerts/$($published.alertId)/requests" @{
    recommendation = "Inspect model demonstration readings"
    requestKind = "inspection"
    executorGroup = "technician"
    priority = "high"
    description = "Inspect the object after a demonstration prediction"
    comment = "Created by the end-to-end smoke check"
    creatorRole = "district_dispatcher"
}
Assert-True ($null -ne $request.id) "existing workflow creates a request from the demo warning"
Assert-True (@(Invoke-RestMethod "$ApiUrl/api/requests" | Where-Object { $_.alertId -eq $published.alertId }).Count -eq 1) "demo request is visible in the existing request API"

Invoke-RestMethod -Method Delete -Uri "$ApiUrl/api/model-demo/results" | Out-Null
$afterObjects = Invoke-RestMethod "$ApiUrl/api/objects"
$afterAlerts = Invoke-RestMethod "$ApiUrl/api/alerts"
$afterRequests = Invoke-RestMethod "$ApiUrl/api/requests"
$afterSms = Invoke-RestMethod "$ApiUrl/api/sms"

Assert-True ((@($afterObjects.id | Sort-Object) -join ",") -eq ($baselineObjectIds -join ",")) "cleanup preserves every baseline object"
Assert-True ((@($afterAlerts.id | Sort-Object) -join ",") -eq ($baselineAlertIds -join ",")) "cleanup preserves every baseline warning"
Assert-True ($afterRequests.Count -eq $baselineRequests.Count) "cleanup removes the demo request chain only"
Assert-True ($afterSms.Count -eq $baselineSms.Count) "cleanup removes demo SMS only"
Assert-True (@($afterAlerts | Where-Object { $_.isDemo }).Count -eq 0) "cleanup leaves no demo warnings"

Write-Host "`nEnd-to-end model demonstration smoke check passed."
