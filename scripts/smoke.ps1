param([string]$ApiUrl = "http://localhost:5000")

$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
    Write-Host "OK: $Message"
}

for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod "$ApiUrl/health"
        if ($health.status -eq "ok") { break }
    } catch {
        if ($attempt -eq 30) { throw "API did not start within 60 seconds" }
        Start-Sleep -Seconds 2
    }
}

$objects = Invoke-RestMethod "$ApiUrl/api/objects"
$alerts = Invoke-RestMethod "$ApiUrl/api/alerts"
$sms = Invoke-RestMethod "$ApiUrl/api/sms"
$levels = @($alerts | ForEach-Object { $_.level } | Sort-Object -Unique)

Assert-True ($objects.Count -ge 4) "demo objects are loaded"
Assert-True (@($levels | Where-Object { $_ -in @("green", "yellow", "red", "black") }).Count -eq 4) "GREEN, YELLOW, RED and BLACK are available"

$main = Invoke-RestMethod "$ApiUrl/api/alerts/11111111-1111-1111-1111-111111111111"
$history = @($main.history | ForEach-Object { $_.toLevel })
Assert-True (($history -join ",") -eq "green,yellow,red,black,red") "escalation and de-escalation are deterministic"
Assert-True (@($main.channels | Where-Object { $null -eq $_.picketSortKey }).Count -ge 1) "channel without a picket is preserved"
Assert-True (@($main.channels | Where-Object { $_.deviceAgeYears -gt 0 -and $_.ageSource }).Count -eq $main.channels.Count) "device age and source are present"
Assert-True (@($sms | Where-Object { $_.alertLevel -eq "black" -and $_.role -eq "ResponseTeam" }).Count -ge 1) "response team receives BLACK"
Assert-True (@($sms | Where-Object { $_.alertLevel -ne "black" -and $_.role -eq "ResponseTeam" }).Count -eq 0) "response team receives no lower-level SMS"

$decision = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/alerts/$($main.id)/decision" -ContentType "application/json" -Body '{"decision":"maintenance","comment":"smoke-check"}'
Assert-True ($null -ne $decision.id) "decision is stored as a future label"

$request = Invoke-RestMethod -Method Post -Uri "$ApiUrl/api/alerts/$($main.id)/requests" -ContentType "application/json" -Body '{"recommendation":"Smoke scenario check"}'
Assert-True ($null -ne $request.id) "request is created from an alert"

Write-Host "`nEnd-to-end smoke check passed."
