using FireRisk.Api.Domain;
using System.Text.Json;

namespace FireRisk.Api.Tests;

public sealed class BusinessRulesTests
{
    [Theory]
    [InlineData(AlertLevel.Green, RecipientRole.OdsDispatcher)]
    [InlineData(AlertLevel.Yellow, RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher)]
    [InlineData(AlertLevel.Red, RecipientRole.Technician | RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher)]
    [InlineData(AlertLevel.Black, RecipientRole.Technician | RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher | RecipientRole.ResponseTeam)]
    public void Recipient_matrix_is_exact(AlertLevel level, RecipientRole expected)
    {
        Assert.Equal(expected, SmsPolicy.Recipients(level));
    }

    [Fact]
    public void Duplicate_sms_is_blocked_during_cooldown_unless_forced()
    {
        var now = DateTimeOffset.Parse("2026-09-27T12:00:00Z");
        var lastSentAt = now.AddMinutes(-10);

        Assert.False(SmsPolicy.CanSend(lastSentAt, now, TimeSpan.FromMinutes(30), force: false));
        Assert.True(SmsPolicy.CanSend(lastSentAt, now, TimeSpan.FromMinutes(30), force: true));
    }

    [Theory]
    [InlineData(MaintenanceStatus.New, MaintenanceStatus.UnderReview, true)]
    [InlineData(MaintenanceStatus.InProgress, MaintenanceStatus.Completed, true)]
    [InlineData(MaintenanceStatus.Completed, MaintenanceStatus.InProgress, false)]
    [InlineData(MaintenanceStatus.Rejected, MaintenanceStatus.Scheduled, false)]
    public void Request_status_transition_is_controlled(
        MaintenanceStatus from,
        MaintenanceStatus to,
        bool expected)
    {
        Assert.Equal(expected, MaintenanceWorkflow.CanTransition(from, to));
    }

    [Fact]
    public void Failed_ml_call_returns_last_prediction_as_stale()
    {
        var last = new StoredPrediction(
            "model-v1",
            DateTimeOffset.Parse("2026-09-27T10:00:00Z"),
            0.1,
            0.2,
            0.3,
            0.4,
            false);

        var result = PredictionFallback.FromFailure(last);

        Assert.True(result.Stale);
        Assert.Equal(last.CalculatedAt, result.CalculatedAt);
        Assert.Equal("model-v1", result.ModelVersion);
    }

    [Fact]
    public void Ml_contract_accepts_python_snake_case()
    {
        const string json = """
            {"model_version":"v2","calculated_at":"2026-09-27T12:00:00Z",
             "p_now":0.1,"p_6h":0.2,"p_12h":0.3,"p_24h":0.4,
             "decisions":{"now":false,"6h":true},"factors":[]}
            """;

        var value = JsonSerializer.Deserialize<MlPrediction>(json);

        Assert.NotNull(value);
        Assert.Equal("v2", value.ModelVersion);
        Assert.Equal(0.4, value.P24h);
    }
}
