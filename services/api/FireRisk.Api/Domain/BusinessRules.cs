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

public sealed record NotificationRecipient(string Id, string Name, ExecutorGroup Group, string District);

public static class RequestNotificationPolicy
{
    private static readonly NotificationRecipient[] Technicians =
    [
        new("tech-ivanov", "Илья Сергеевич Иванов", ExecutorGroup.Technician, "САО"),
        new("tech-petrova", "Мария Андреевна Петрова", ExecutorGroup.Technician, "САО"),
        new("tech-sokolov", "Алексей Дмитриевич Соколов", ExecutorGroup.Technician, "ЦАО"),
        new("tech-sokolov", "Алексей Дмитриевич Соколов", ExecutorGroup.Technician, "ЮАО")
    ];

    private static readonly NotificationRecipient[] ResponseTeam =
    [
        new("response-orlova", "Наталья Викторовна Орлова", ExecutorGroup.ResponseTeam, "ЮАО"),
        new("response-volkov", "Сергей Павлович Волков", ExecutorGroup.ResponseTeam, "ЮАО")
    ];

    public static IReadOnlyList<NotificationRecipient> Recipients(AlertLevel level, string district)
    {
        if (level is not AlertLevel.Red and not AlertLevel.Black) return [];
        var technicians = Technicians.Where(recipient => recipient.District == district);
        return level == AlertLevel.Black
            ? technicians.Concat(ResponseTeam.Where(recipient => recipient.District == district)).DistinctBy(recipient => recipient.Id).ToArray()
            : technicians.ToArray();
    }
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

public enum MaintenanceStatus { New, InProgress, Completed, Rejected }

public static class MaintenanceWorkflow
{
    public static bool CanTransition(MaintenanceStatus from, MaintenanceStatus to) => from switch
    {
        MaintenanceStatus.New => to is MaintenanceStatus.InProgress or MaintenanceStatus.Rejected,
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
