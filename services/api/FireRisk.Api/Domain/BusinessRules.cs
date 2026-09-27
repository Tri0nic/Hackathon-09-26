namespace FireRisk.Api.Domain;

public enum AlertLevel { Green, Yellow, Red, Black }

[Flags]
public enum RecipientRole
{
    None = 0,
    Technician = 1,
    DistrictDispatcher = 2,
    OdsDispatcher = 4,
    ResponseTeam = 8
}

public static class SmsPolicy
{
    public static RecipientRole Recipients(AlertLevel level) => level switch
    {
        AlertLevel.Green => RecipientRole.OdsDispatcher,
        AlertLevel.Yellow => RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher,
        AlertLevel.Red => RecipientRole.Technician | RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher,
        AlertLevel.Black => RecipientRole.Technician | RecipientRole.DistrictDispatcher | RecipientRole.OdsDispatcher | RecipientRole.ResponseTeam,
        _ => RecipientRole.None
    };

    public static bool CanSend(
        DateTimeOffset? lastSentAt,
        DateTimeOffset now,
        TimeSpan cooldown,
        bool force) => force || lastSentAt is null || now - lastSentAt >= cooldown;
}

public enum MaintenanceStatus { New, UnderReview, Scheduled, InProgress, Completed, Rejected }

public static class MaintenanceWorkflow
{
    public static bool CanTransition(MaintenanceStatus from, MaintenanceStatus to) => from switch
    {
        MaintenanceStatus.New => to is MaintenanceStatus.UnderReview or MaintenanceStatus.Rejected,
        MaintenanceStatus.UnderReview => to is MaintenanceStatus.Scheduled or MaintenanceStatus.Rejected,
        MaintenanceStatus.Scheduled => to is MaintenanceStatus.InProgress or MaintenanceStatus.Rejected,
        MaintenanceStatus.InProgress => to is MaintenanceStatus.Completed or MaintenanceStatus.Rejected,
        _ => false
    };
}

public sealed record StoredPrediction(
    string ModelVersion,
    DateTimeOffset CalculatedAt,
    double PNow,
    double P6h,
    double P12h,
    double P24h,
    bool Stale);

public static class PredictionFallback
{
    public static StoredPrediction FromFailure(StoredPrediction last) => last with { Stale = true };
}
