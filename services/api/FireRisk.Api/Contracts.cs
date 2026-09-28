using FireRisk.Api.Domain;
using System.Text.Json.Serialization;

namespace FireRisk.Api;

public sealed record DecisionRequest(string Decision, string? Comment);
public sealed record CreateMaintenanceRequest(
    string? Recommendation,
    RequestKind RequestKind,
    ExecutorGroup ExecutorGroup,
    RequestPriority Priority,
    string Description,
    DateTimeOffset? DueAt,
    string? Comment,
    RequestCreatorRole CreatorRole);
public sealed record ClaimMaintenanceRequest(string EmployeeId, string EmployeeName, ExecutorGroup ExecutorGroup);
public sealed record ExecuteRequestAction(
    string EmployeeId,
    string EmployeeName,
    ExecutorRequestAction Action,
    string? Comment);
public sealed record ChangeRequestStatus(MaintenanceStatus Status);
public sealed record CreatedMaintenanceRequest(Guid Id, string PublicId);
public sealed record PredictRequest(Dictionary<string, double?> Features, int TopK = 5);

public sealed record MlFactor(string Horizon, string Feature, double Value, double Contribution);

public sealed record MlPrediction(
    [property: JsonPropertyName("model_version")] string ModelVersion,
    [property: JsonPropertyName("calculated_at")] DateTimeOffset CalculatedAt,
    [property: JsonPropertyName("p_now")] double PNow,
    [property: JsonPropertyName("p_6h")] double P6h,
    [property: JsonPropertyName("p_12h")] double P12h,
    [property: JsonPropertyName("p_24h")] double P24h,
    Dictionary<string, bool> Decisions,
    IReadOnlyList<MlFactor> Factors,
    bool Stale = false);
