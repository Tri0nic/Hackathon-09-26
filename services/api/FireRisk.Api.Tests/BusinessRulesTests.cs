using FireRisk.Api.Domain;
using System.Text.Json;

namespace FireRisk.Api.Tests;

public sealed class BusinessRulesTests
{
    [Theory]
    [InlineData(RequestCreatorRole.OdsDispatcher, ExecutorGroup.ResponseTeam, RequestPriority.Emergency, true)]
    [InlineData(RequestCreatorRole.OdsDispatcher, ExecutorGroup.Technician, RequestPriority.Normal, false)]
    [InlineData(RequestCreatorRole.DistrictDispatcher, ExecutorGroup.Technician, RequestPriority.Normal, true)]
    public void Request_creation_obeys_dispatcher_permissions(
        RequestCreatorRole creator,
        ExecutorGroup executor,
        RequestPriority priority,
        bool expected)
    {
        Assert.Equal(expected, RequestPolicy.CanCreate(creator, executor, priority));
    }

    [Theory]
    [InlineData(ExecutorGroup.Technician, ExecutorGroup.Technician, null, true)]
    [InlineData(ExecutorGroup.Technician, ExecutorGroup.ResponseTeam, null, false)]
    [InlineData(ExecutorGroup.ResponseTeam, ExecutorGroup.ResponseTeam, "member-1", false)]
    public void Only_matching_group_can_claim_an_unassigned_request(
        ExecutorGroup actorGroup,
        ExecutorGroup requestGroup,
        string? assigneeId,
        bool expected)
    {
        Assert.Equal(expected, RequestPolicy.CanClaim(actorGroup, requestGroup, assigneeId, MaintenanceStatus.New));
    }

    [Fact]
    public void Completed_request_cannot_be_claimed()
    {
        Assert.False(RequestPolicy.CanClaim(ExecutorGroup.Technician, ExecutorGroup.Technician, null, MaintenanceStatus.Completed));
    }

    [Theory]
    [InlineData(ExecutorRequestAction.Comment, "Выполнена диагностика", true)]
    [InlineData(ExecutorRequestAction.Release, "Нужен другой специалист", true)]
    [InlineData(ExecutorRequestAction.Complete, "Заменён датчик", true)]
    [InlineData(ExecutorRequestAction.Cancel, "", false)]
    [InlineData(ExecutorRequestAction.Cancel, "Нет доступа к объекту", true)]
    public void Executor_action_validates_required_comment(ExecutorRequestAction action, string comment, bool expected)
    {
        Assert.Equal(expected, ExecutorActionPolicy.HasValidComment(action, comment));
    }

    [Fact]
    public void Only_current_assignee_can_change_request()
    {
        Assert.True(ExecutorActionPolicy.CanAct("tech-1", "tech-1", MaintenanceStatus.InProgress));
        Assert.False(ExecutorActionPolicy.CanAct("tech-2", "tech-1", MaintenanceStatus.InProgress));
        Assert.False(ExecutorActionPolicy.CanAct("tech-1", "tech-1", MaintenanceStatus.Completed));
    }

    [Fact]
    public void Request_notification_reaches_every_technician()
    {
        var recipients = RequestNotificationPolicy.Recipients(ExecutorGroup.Technician);

        Assert.Equal(new[] { "tech-ivanov", "tech-petrova", "tech-sokolov" }, recipients.Select(x => x.Id));
    }

    [Fact]
    public void Request_notification_reaches_every_response_member()
    {
        var recipients = RequestNotificationPolicy.Recipients(ExecutorGroup.ResponseTeam);

        Assert.Equal(new[] { "response-orlova", "response-volkov" }, recipients.Select(x => x.Id));
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
