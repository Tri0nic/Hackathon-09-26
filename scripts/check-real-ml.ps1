param([string]$MlUrl = "http://localhost:8000")

$ErrorActionPreference = "Stop"
$expectedVersion = "catboost-e87d5604945b"

$model = Invoke-RestMethod "$MlUrl/ml/models/current"
if ($model.modelVersion -ne $expectedVersion) {
    throw "Expected $expectedVersion, got $($model.modelVersion)"
}
if ($model.artifact -ne "catboost-synthetic-v1") {
    throw "Unexpected artifact: $($model.artifact)"
}
if ($model.rocAuc -le 0 -or $model.precision -le 0 -or $model.recall -le 0) {
    throw "Model metrics are missing"
}

$body = @{
    features = @{
        activity_ratio_24h = 1.25
        alarm_count_5m = 3
        smoke_heat_5m = 1
    }
    topK = 3
} | ConvertTo-Json -Depth 4
$prediction = Invoke-RestMethod -Method Post -Uri "$MlUrl/ml/predict" -ContentType "application/json" -Body $body

if ($prediction.model_version -ne $expectedVersion) {
    throw "Prediction used $($prediction.model_version)"
}
if (-not ($prediction.p_now -le $prediction.p_6h -and $prediction.p_6h -le $prediction.p_12h -and $prediction.p_12h -le $prediction.p_24h)) {
    throw "Forecast probabilities are not monotonic"
}
if (@($prediction.factors).Count -eq 0) {
    throw "Prediction factors are missing"
}

Write-Host "OK: catboost-synthetic-v1 is the only active ML artifact"
