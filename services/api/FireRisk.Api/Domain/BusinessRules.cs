namespace FireRisk.Api.Domain;

public enum AlertLevel { Green, Yellow, Red, Black }

public enum RequestCreatorRole { DistrictDispatcher, OdsDispatcher }
public enum ExecutorGroup { Technician, ResponseTeam }
public enum RequestPriority { Normal, High, Emergency }
public enum RequestKind { Inspection, Repair, Emergency }

public static class RequestPolicy
{
    public static bool CanCreate(RequestCreatorRole creator, ExecutorGroup executor, RequestPriority priority) =>
        creator == RequestCreatorRole.DistrictDispatcher ||
        creator == RequestCreatorRole.OdsDispatcher && executor == ExecutorGroup.ResponseTeam && priority == RequestPriority.Emergency;

    public static bool CanClaim(ExecutorGroup actorGroup, ExecutorGroup requestGroup, string? assigneeId, MaintenanceStatus status) =>
        actorGroup == requestGroup && string.IsNullOrWhiteSpace(assigneeId) && status is not MaintenanceStatus.Completed and not MaintenanceStatus.Rejected;
}

public sealed record NotificationRecipient(string Id, string Name);

public static class RequestNotificationPolicy
{
    private static readonly NotificationRecipient[] Technicians =
    [
        new("tech-ivanov", "Илья Сергеевич Иванов"),
        new("tech-petrova", "Мария Андреевна Петрова"),
        new("tech-sokolov", "Алексей Дмитриевич Соколов")
    ];

    private static readonly NotificationRecipient[] ResponseTeam =
    [
        new("response-orlova", "Наталья Викторовна Орлова"),
        new("response-volkov", "Сергей Павлович Волков")
    ];

    public static IReadOnlyList<NotificationRecipient> Recipients(ExecutorGroup group) =>
        group == ExecutorGroup.Technician ? Technicians : ResponseTeam;
}

public enum ClaimRequestResult { Claimed, AlreadyAssigned, NotFound }
public enum ExecutorRequestAction { Comment, Release, Complete, Cancel }
public enum ExecutorActionResult { Updated, Forbidden, NotFound, CommentRequired }

public static class ExecutorActionPolicy
{
    public static bool CanAct(string actorId, string? assigneeId, MaintenanceStatus status) =>
        !string.IsNullOrWhiteSpace(actorId) && actorId == assigneeId && status == MaintenanceStatus.InProgress;

    public static bool HasValidComment(ExecutorRequestAction action, string? comment) =>
        action != ExecutorRequestAction.Cancel || !string.IsNullOrWhiteSpace(comment);
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
