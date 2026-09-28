using System.Text.Json;
using System.Security.Cryptography;
using System.Globalization;
using FireRisk.Api.Domain;
using Npgsql;

namespace FireRisk.Api;

public interface IModelDemoPublicationStore
{
    Task<Guid> PublishAsync(Guid calculationId, ModelDemoScenario scenario, MlPrediction prediction, CancellationToken cancellationToken);
    Task DeleteResultsAsync(CancellationToken cancellationToken);
}

public sealed class PgStore(NpgsqlDataSource dataSource) : IModelDemoPublicationStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public async Task MigrateAsync(CancellationToken cancellationToken = default)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Migrations", "001_initial.sql");
        await using var command = dataSource.CreateCommand(await File.ReadAllTextAsync(path, cancellationToken));
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        await using var command = dataSource.CreateCommand("select 1");
        return Convert.ToInt32(await command.ExecuteScalarAsync(cancellationToken)) == 1;
    }

    public Task<JsonElement> GetDashboardAsync(CancellationToken ct) => JsonAsync("""
        select json_build_object(
          'objects', (select count(*) from infrastructure_objects),
          'activeAlerts', (select count(*) from risk_alerts where current),
          'openRequests', (select count(*) from maintenance_requests where status not in ('completed','rejected')),
          'lastCalculatedAt', (select max(calculated_at) from risk_predictions),
          'alertsByLevel', coalesce((select json_object_agg(level, amount) from
            (select level, count(*) amount from risk_alerts where current group by level) x), '{}'::json)
        )::text
        """, ct);

    public Task<JsonElement> GetObjectsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x.name), '[]'::json)::text from (
          select o.id, o.name, o.district,
            (select count(*) from data_channels c where c.object_id=o.id) "channelCount",
            coalesce((select a.level from risk_alerts a where a.object_id=o.id and a.current order by a.calculated_at desc limit 1), 'green') level,
            coalesce((select a.probability from risk_alerts a where a.object_id=o.id and a.current order by a.calculated_at desc limit 1), 0) probability,
            coalesce((select json_agg(json_build_object(
              'id', c.id, 'name', c.name, 'sensorType', c.sensor_type,
              'picketRaw', c.picket_raw, 'picketSortKey', c.picket_sort_key,
              'value', c.display_value, 'state', c.display_state,
              'deviceAgeYears', c.device_age_years, 'ageSource', c.age_source,
              'maintenanceNote', c.maintenance_note, 'metadataSource', c.metadata_source
            ) order by c.picket_sort_key nulls last) from data_channels c where c.object_id=o.id), '[]'::json) channels
          from infrastructure_objects o
        ) x
        """, ct);

    public Task<JsonElement> GetObjectAsync(string id, CancellationToken ct) => JsonAsync("""
        select coalesce((select json_build_object(
          'id', o.id, 'name', o.name,
          'channels', coalesce((select json_agg(json_build_object(
            'id', c.id, 'sensorType', c.sensor_type, 'name', c.name,
            'picketRaw', c.picket_raw, 'picketSortKey', c.picket_sort_key,
            'value', c.display_value, 'state', c.display_state,
            'deviceAgeYears', c.device_age_years, 'ageSource', c.age_source, 'maintenanceNote', c.maintenance_note,
            'metadataSource', c.metadata_source
          ) order by c.picket_sort_key nulls last, c.name) from data_channels c where c.object_id=o.id), '[]'::json)
        ) from infrastructure_objects o where o.id=@id), 'null'::json)::text
        """, ct, new NpgsqlParameter("id", id));

    public Task<JsonElement> GetPicketsAsync(string id, CancellationToken ct) => JsonAsync("""
        select json_build_object(
          'pickets', coalesce((select json_agg(row_to_json(x) order by x."picketSortKey") from (
            select id, name, sensor_type "sensorType", picket_raw "picketRaw", picket_sort_key "picketSortKey"
            from data_channels where object_id=@id and picket_sort_key is not null
          ) x), '[]'::json),
          'withoutPicket', coalesce((select json_agg(row_to_json(x)) from (
            select id, name, sensor_type "sensorType" from data_channels
            where object_id=@id and picket_sort_key is null
          ) x), '[]'::json)
        )::text
        """, ct, new NpgsqlParameter("id", id));

    public Task<JsonElement> GetAlertsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x."calculatedAt" desc), '[]'::json)::text from (
          select a.id, a.episode_id "episodeId", a.object_id "objectId", o.name "objectName",
            a.alert_kind kind, a.level, a.horizon, a.probability,
            a.p_now "pNow", a.p_6h "p6h", a.p_12h "p12h", a.p_24h "p24h",
            a.calculated_at "calculatedAt", a.model_version "modelVersion", a.stale, a.current, a.is_demo "isDemo",
            (select min(c.picket_sort_key) from data_channels c where c.object_id=a.object_id) "picketFrom",
            (select max(c.picket_sort_key) from data_channels c where c.object_id=a.object_id) "picketTo",
            a.factors, a.recommendation, a.context,
            coalesce((select json_agg(json_build_object(
              'id', c.id, 'name', c.name, 'sensorType', c.sensor_type,
              'picketRaw', c.picket_raw, 'picketSortKey', c.picket_sort_key,
              'value', c.display_value, 'state', c.display_state,
              'deviceAgeYears', c.device_age_years, 'ageSource', c.age_source,
              'maintenanceNote', c.maintenance_note, 'metadataSource', c.metadata_source
            ) order by c.picket_sort_key nulls last) from data_channels c where c.object_id=a.object_id), '[]'::json) channels,
            coalesce((select json_agg(json_build_object(
              'fromLevel', h.from_level, 'toLevel', h.to_level, 'changedAt', h.changed_at
            ) order by h.changed_at) from alert_level_history h where h.alert_id=a.id), '[]'::json) history,
            coalesce((select json_agg(json_build_object(
              'decision', d.decision, 'comment', d.comment, 'decidedAt', d.decided_at
            ) order by d.decided_at desc) from dispatcher_decisions d where d.alert_id=a.id), '[]'::json) decisions
          from risk_alerts a join infrastructure_objects o on o.id=a.object_id
        ) x
        """, ct);

    public Task<JsonElement> GetAlertAsync(Guid id, CancellationToken ct) => JsonAsync("""
        select coalesce((select json_build_object(
          'id', a.id, 'episodeId', a.episode_id, 'objectId', a.object_id, 'objectName', o.name,
          'level', a.level, 'horizon', a.horizon, 'probability', a.probability,
          'pNow', a.p_now, 'p6h', a.p_6h, 'p12h', a.p_12h, 'p24h', a.p_24h,
          'calculatedAt', a.calculated_at, 'modelVersion', a.model_version, 'stale', a.stale, 'isDemo', a.is_demo,
          'kind', a.alert_kind, 'factors', a.factors, 'recommendation', a.recommendation, 'context', a.context,
          'picketFrom', (select min(picket_sort_key) from data_channels where object_id=a.object_id),
          'picketTo', (select max(picket_sort_key) from data_channels where object_id=a.object_id),
          'channels', coalesce((select json_agg(json_build_object(
             'id', c.id, 'name', c.name, 'sensorType', c.sensor_type,
             'picketRaw', c.picket_raw, 'picketSortKey', c.picket_sort_key,
             'value', c.display_value, 'state', c.display_state,
             'deviceAgeYears', c.device_age_years, 'ageSource', c.age_source, 'maintenanceNote', c.maintenance_note,
             'metadataSource', c.metadata_source
          ) order by c.picket_sort_key nulls last) from data_channels c where c.object_id=a.object_id), '[]'::json),
          'history', coalesce((select json_agg(json_build_object(
             'fromLevel', h.from_level, 'toLevel', h.to_level, 'changedAt', h.changed_at
          ) order by h.changed_at) from alert_level_history h where h.alert_id=a.id), '[]'::json),
          'decisions', coalesce((select json_agg(row_to_json(d) order by d."decidedAt" desc) from (
             select decision, comment, decided_at "decidedAt" from dispatcher_decisions where alert_id=a.id
          ) d), '[]'::json)
        ) from risk_alerts a join infrastructure_objects o on o.id=a.object_id where a.id=@id), 'null'::json)::text
        """, ct, new NpgsqlParameter("id", id));

    public async Task<Guid> AddDecisionAsync(Guid alertId, string decision, string? comment, CancellationToken ct)
    {
        var id = Guid.NewGuid();
        await using var command = dataSource.CreateCommand("""
            insert into dispatcher_decisions(id, alert_id, episode_id, object_id, decision, comment, decided_at)
            select @id, a.id, a.episode_id, a.object_id, @decision, @comment, now()
            from risk_alerts a where a.id=@alertId
            """);
        command.Parameters.AddWithValue("id", id);
        command.Parameters.AddWithValue("alertId", alertId);
        command.Parameters.AddWithValue("decision", decision);
        command.Parameters.AddWithValue("comment", (object?)comment ?? DBNull.Value);
        if (await command.ExecuteNonQueryAsync(ct) == 0) throw new KeyNotFoundException("Alert not found");
        return id;
    }

    public async Task<CreatedMaintenanceRequest> AddRequestAsync(Guid alertId, CreateMaintenanceRequest request, CancellationToken ct)
    {
        if (!RequestPolicy.CanCreate(request.CreatorRole, request.ExecutorGroup, request.Priority))
            throw new InvalidOperationException("This dispatcher cannot create the requested assignment");
        var id = Guid.NewGuid();
        await using var connection = await dataSource.OpenConnectionAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        string level;
        string district;
        await using (var context = new NpgsqlCommand("select a.level, o.district from risk_alerts a join infrastructure_objects o on o.id=a.object_id where a.id=@alertId", connection, transaction))
        {
            context.Parameters.AddWithValue("alertId", alertId);
            await using var reader = await context.ExecuteReaderAsync(ct);
            if (!await reader.ReadAsync(ct)) throw new KeyNotFoundException("Alert not found");
            level = reader.GetString(0);
            district = reader.GetString(1);
        }
        var publicId = await NextPublicRequestIdAsync(connection, transaction, ct);
        await using var command = new NpgsqlCommand("""
            insert into maintenance_requests(id, public_id, alert_id, object_id, picket, factors, recommendation,
              request_kind, executor_group, priority, description, due_at, comment, creator_role,
              status, created_at, updated_at)
            select @id, @publicId, a.id, a.object_id,
              (select min(picket_raw) from data_channels where object_id=a.object_id and picket_sort_key is not null),
              a.factors, coalesce(@recommendation, a.recommendation), @kind, @executor, @priority,
              @description, @dueAt, @comment, @creator, 'new', now(), now()
            from risk_alerts a where a.id=@alertId
            """, connection, transaction);
        command.Parameters.AddWithValue("id", id);
        command.Parameters.AddWithValue("publicId", publicId);
        command.Parameters.AddWithValue("alertId", alertId);
        command.Parameters.AddWithValue("recommendation", (object?)request.Recommendation ?? DBNull.Value);
        command.Parameters.AddWithValue("kind", EnumName(request.RequestKind));
        command.Parameters.AddWithValue("executor", EnumName(request.ExecutorGroup));
        command.Parameters.AddWithValue("priority", EnumName(request.Priority));
        command.Parameters.AddWithValue("description", request.Description.Trim());
        command.Parameters.AddWithValue("dueAt", (object?)request.DueAt ?? DBNull.Value);
        command.Parameters.AddWithValue("comment", (object?)request.Comment ?? DBNull.Value);
        command.Parameters.AddWithValue("creator", EnumName(request.CreatorRole));
        if (await command.ExecuteNonQueryAsync(ct) == 0) throw new KeyNotFoundException("Alert not found");

        foreach (var recipient in RequestNotificationPolicy.Recipients(Enum.Parse<AlertLevel>(level, true), district))
        {
            await using var sms = new NpgsqlCommand("""
                insert into sms_notifications(id, episode_id, alert_level, recipient_id, recipient_name, role,
                  request_id, sent_at, content, status, processing_status)
                select @smsId, a.episode_id, a.level, @recipientId, @recipientName, @role,
                  @requestId, now(), @content, 'delivered', 'new'
                from risk_alerts a where a.id=@alertId
                """, connection, transaction);
            sms.Parameters.AddWithValue("smsId", Guid.NewGuid());
            sms.Parameters.AddWithValue("recipientId", recipient.Id);
            sms.Parameters.AddWithValue("recipientName", recipient.Name);
            sms.Parameters.AddWithValue("role", recipient.Group == ExecutorGroup.Technician ? "Technician" : "ResponseTeam");
            sms.Parameters.AddWithValue("requestId", id);
            sms.Parameters.AddWithValue("alertId", alertId);
            sms.Parameters.AddWithValue("content", $"Создана заявка: {request.Description.Trim()}");
            await sms.ExecuteNonQueryAsync(ct);
        }
        await transaction.CommitAsync(ct);
        return new CreatedMaintenanceRequest(id, publicId);
    }

    public Task<JsonElement> GetRequestsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x."createdAt" desc), '[]'::json)::text from (
          select r.id, r.public_id "publicId", r.alert_id "alertId", r.object_id "objectId", o.name "objectName", r.picket,
            r.factors, r.recommendation, r.request_kind "requestKind", r.executor_group "executorGroup",
            r.priority, r.description, r.due_at "dueAt", r.comment, r.creator_role "creatorRole",
            r.assignee_id "assigneeId", r.assignee_name "assigneeName",
            coalesce((select json_agg(json_build_object(
              'id', c.id, 'employeeId', c.employee_id, 'employeeName', c.employee_name,
              'text', c.comment_text, 'createdAt', c.created_at
            ) order by c.created_at) from request_comments c where c.request_id=r.id), '[]'::json) comments,
            r.status, r.created_at "createdAt", r.updated_at "updatedAt"
          from maintenance_requests r join infrastructure_objects o on o.id=r.object_id
        ) x
        """, ct);

    public async Task<bool> ChangeRequestStatusAsync(Guid id, MaintenanceStatus requested, CancellationToken ct)
    {
        await using var read = dataSource.CreateCommand("select status from maintenance_requests where id=@id");
        read.Parameters.AddWithValue("id", id);
        var currentValue = await read.ExecuteScalarAsync(ct);
        if (currentValue is not string current) return false;
        var from = ParseStatus(current);
        if (!MaintenanceWorkflow.CanTransition(from, requested))
            throw new InvalidOperationException($"Invalid status transition: {current} -> {StatusName(requested)}");
        await using var update = dataSource.CreateCommand("update maintenance_requests set status=@status, updated_at=now() where id=@id");
        update.Parameters.AddWithValue("id", id);
        update.Parameters.AddWithValue("status", StatusName(requested));
        await update.ExecuteNonQueryAsync(ct);
        if (requested == MaintenanceStatus.Completed)
        {
            await using var sms = dataSource.CreateCommand("""
                update sms_notifications set processing_status='completed'
                where request_id=@id and status='delivered'
                """);
            sms.Parameters.AddWithValue("id", id);
            await sms.ExecuteNonQueryAsync(ct);
        }
        return true;
    }

    public async Task<ClaimRequestResult> ClaimRequestAsync(Guid id, string employeeId, string employeeName, ExecutorGroup group, CancellationToken ct)
    {
        await using var connection = await dataSource.OpenConnectionAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        await using var command = new NpgsqlCommand("""
            update maintenance_requests
            set assignee_id=@employeeId, assignee_name=@employeeName, status='in_progress', updated_at=now()
            where id=@id and assignee_id is null and executor_group=@executor and status not in ('completed','rejected')
            """, connection, transaction);
        command.Parameters.AddWithValue("id", id);
        command.Parameters.AddWithValue("employeeId", employeeId);
        command.Parameters.AddWithValue("employeeName", employeeName);
        command.Parameters.AddWithValue("executor", EnumName(group));
        if (await command.ExecuteNonQueryAsync(ct) == 1)
        {
            await using var sms = new NpgsqlCommand("""
                update sms_notifications set assignee_name=@employeeName, processing_status='in_progress'
                where request_id=@id and status='delivered'
                """, connection, transaction);
            sms.Parameters.AddWithValue("id", id);
            sms.Parameters.AddWithValue("employeeName", employeeName);
            await sms.ExecuteNonQueryAsync(ct);
            await transaction.CommitAsync(ct);
            return ClaimRequestResult.Claimed;
        }

        await transaction.RollbackAsync(ct);
        await using var exists = dataSource.CreateCommand("select exists(select 1 from maintenance_requests where id=@id)");
        exists.Parameters.AddWithValue("id", id);
        return Convert.ToBoolean(await exists.ExecuteScalarAsync(ct)) ? ClaimRequestResult.AlreadyAssigned : ClaimRequestResult.NotFound;
    }

    public async Task<ExecutorActionResult> ExecuteRequestActionAsync(Guid id, ExecuteRequestAction request, CancellationToken ct)
    {
        if (!ExecutorActionPolicy.HasValidComment(request.Action, request.Comment))
            return ExecutorActionResult.CommentRequired;

        await using var connection = await dataSource.OpenConnectionAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        string? assigneeId;
        string? status;
        await using (var read = new NpgsqlCommand("select assignee_id, status from maintenance_requests where id=@id for update", connection, transaction))
        {
            read.Parameters.AddWithValue("id", id);
            await using var reader = await read.ExecuteReaderAsync(ct);
            if (!await reader.ReadAsync(ct)) return ExecutorActionResult.NotFound;
            assigneeId = reader.IsDBNull(0) ? null : reader.GetString(0);
            status = reader.GetString(1);
        }

        if (!ExecutorActionPolicy.CanAct(request.EmployeeId, assigneeId, ParseStatus(status)))
            return ExecutorActionResult.Forbidden;

        if (!string.IsNullOrWhiteSpace(request.Comment))
        {
            await using var comment = new NpgsqlCommand("""
                insert into request_comments(id, request_id, employee_id, employee_name, comment_text, created_at)
                values(@id, @requestId, @employeeId, @employeeName, @text, now())
                """, connection, transaction);
            comment.Parameters.AddWithValue("id", Guid.NewGuid());
            comment.Parameters.AddWithValue("requestId", id);
            comment.Parameters.AddWithValue("employeeId", request.EmployeeId);
            comment.Parameters.AddWithValue("employeeName", request.EmployeeName);
            comment.Parameters.AddWithValue("text", request.Comment.Trim());
            await comment.ExecuteNonQueryAsync(ct);
        }

        var (nextStatus, clearAssignee, smsStatus) = request.Action switch
        {
            ExecutorRequestAction.Release => ("new", true, "new"),
            ExecutorRequestAction.Complete => ("completed", false, "completed"),
            ExecutorRequestAction.Cancel => ("rejected", false, "cancelled"),
            _ => ("in_progress", false, "in_progress")
        };
        await using (var update = new NpgsqlCommand("""
            update maintenance_requests
            set status=@status,
                assignee_id=case when @clear then null else assignee_id end,
                assignee_name=case when @clear then null else assignee_name end,
                updated_at=now()
            where id=@id
            """, connection, transaction))
        {
            update.Parameters.AddWithValue("id", id);
            update.Parameters.AddWithValue("status", nextStatus);
            update.Parameters.AddWithValue("clear", clearAssignee);
            await update.ExecuteNonQueryAsync(ct);
        }
        await using (var sms = new NpgsqlCommand("""
            update sms_notifications
            set processing_status=@status,
                assignee_name=case when @clear then null else assignee_name end
            where request_id=@id and status='delivered'
            """, connection, transaction))
        {
            sms.Parameters.AddWithValue("id", id);
            sms.Parameters.AddWithValue("status", smsStatus);
            sms.Parameters.AddWithValue("clear", clearAssignee);
            await sms.ExecuteNonQueryAsync(ct);
        }
        await transaction.CommitAsync(ct);
        return ExecutorActionResult.Updated;
    }

    public Task<JsonElement> GetSmsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x."sentAt" desc), '[]'::json)::text from (
          select s.id, s.episode_id "episodeId",
            case
              when s.alert_level = 'black' then 'Критическое событие · ' || coalesce(o.name, 'Объект не указан')
              else 'Пожарный риск · ' || coalesce(o.name, 'Объект не указан')
            end "episodeTitle",
            s.alert_level "alertLevel", s.recipient_id "recipientId",
            case s.role
              when 'Technician' then 'Техник'
              when 'DistrictDispatcher' then 'Диспетчер района'
              when 'OdsDispatcher' then 'Диспетчер ОДС'
              when 'ResponseTeam' then 'Группа реагирования'
              else s.role
            end role,
            coalesce(s.recipient_name, case s.role
              when 'Technician' then 'Техник объекта'
              when 'DistrictDispatcher' then 'Диспетчер района'
              when 'OdsDispatcher' then 'Дежурный диспетчер ОДС'
              when 'ResponseTeam' then 'Группа немедленного реагирования'
              else s.recipient_id
            end) "recipientName",
            s.sent_at "sentAt", s.content,
            coalesce(a.factors->0->>'label', a.recommendation, 'Причина не указана') "incidentSummary",
            coalesce(s.assignee_name, r.assignee_name) "assigneeName", s.status, s.processing_status "processingStatus",
            s.request_id "requestId"
          from sms_notifications s
          left join risk_alerts a on a.episode_id = s.episode_id and a.current
          left join infrastructure_objects o on o.id = a.object_id
          left join maintenance_requests r on r.id = s.request_id
          where s.role in ('Technician', 'ResponseTeam')
        ) x
        """, ct);

    public async Task<StoredPrediction?> GetLastPredictionAsync(string objectId, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand("""
            select model_version, calculated_at, p_now, p_6h, p_12h, p_24h
            from risk_predictions where object_id=@objectId order by calculated_at desc limit 1
            """);
        command.Parameters.AddWithValue("objectId", objectId);
        await using var reader = await command.ExecuteReaderAsync(ct);
        if (!await reader.ReadAsync(ct)) return null;
        return new StoredPrediction(reader.GetString(0), new DateTimeOffset(reader.GetDateTime(1)),
            reader.GetDouble(2), reader.GetDouble(3), reader.GetDouble(4), reader.GetDouble(5), false);
    }

    public async Task MarkCurrentAlertStaleAsync(string objectId, CancellationToken ct)
    {
        await using var command = dataSource.CreateCommand(
            "update risk_alerts set stale=true where object_id=@objectId and current");
        command.Parameters.AddWithValue("objectId", objectId);
        await command.ExecuteNonQueryAsync(ct);
    }

    public async Task<Guid?> SavePredictionAsync(string objectId, MlPrediction prediction, CancellationToken ct)
    {
        await using var connection = await dataSource.OpenConnectionAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        await using (var insertPrediction = new NpgsqlCommand("""
            insert into risk_predictions(id, object_id, model_version, calculated_at, p_now, p_6h, p_12h, p_24h, factors)
            values (@id,@objectId,@model,@at,@pNow,@p6,@p12,@p24,@factors::jsonb)
            """, connection, transaction))
        {
            insertPrediction.Parameters.AddWithValue("id", Guid.NewGuid());
            insertPrediction.Parameters.AddWithValue("objectId", objectId);
            insertPrediction.Parameters.AddWithValue("model", prediction.ModelVersion);
            insertPrediction.Parameters.AddWithValue("at", prediction.CalculatedAt);
            insertPrediction.Parameters.AddWithValue("pNow", prediction.PNow);
            insertPrediction.Parameters.AddWithValue("p6", prediction.P6h);
            insertPrediction.Parameters.AddWithValue("p12", prediction.P12h);
            insertPrediction.Parameters.AddWithValue("p24", prediction.P24h);
            insertPrediction.Parameters.AddWithValue("factors", JsonSerializer.Serialize(prediction.Factors, JsonOptions));
            await insertPrediction.ExecuteNonQueryAsync(ct);
        }

        var risk = SelectRisk(prediction);
        if (risk is null)
        {
            await transaction.CommitAsync(ct);
            return null;
        }

        Guid alertId;
        string episodeId;
        string? oldLevel;
        await using (var current = new NpgsqlCommand("select id, episode_id, level from risk_alerts where object_id=@objectId and current limit 1", connection, transaction))
        {
            current.Parameters.AddWithValue("objectId", objectId);
            await using var reader = await current.ExecuteReaderAsync(ct);
            if (await reader.ReadAsync(ct))
            {
                alertId = reader.GetGuid(0); episodeId = reader.GetString(1); oldLevel = reader.GetString(2);
            }
            else
            {
                alertId = Guid.NewGuid(); episodeId = $"{objectId}-{prediction.CalculatedAt:yyyyMMddHH}"; oldLevel = null;
            }
        }

        var factors = JsonSerializer.Serialize(prediction.Factors, JsonOptions);
        if (oldLevel is null)
        {
            await using var insert = new NpgsqlCommand("""
                insert into risk_alerts(id,episode_id,object_id,level,horizon,probability,p_now,p_6h,p_12h,p_24h,
                  calculated_at,model_version,stale,factors,recommendation,current)
                values(@id,@episode,@objectId,@level,@horizon,@prob,@pNow,@p6,@p12,@p24,@at,@model,false,@factors::jsonb,
                  'Проверить датчики и выполнить профилактический осмотр',true)
                """, connection, transaction);
            AddAlertParameters(insert, alertId, episodeId, objectId, risk.Value, prediction, factors);
            await insert.ExecuteNonQueryAsync(ct);
        }
        else
        {
            await using var update = new NpgsqlCommand("""
                update risk_alerts set level=@level,horizon=@horizon,probability=@prob,p_now=@pNow,p_6h=@p6,p_12h=@p12,p_24h=@p24,
                  calculated_at=@at,model_version=@model,stale=false,factors=@factors::jsonb where id=@id
                """, connection, transaction);
            AddAlertParameters(update, alertId, episodeId, objectId, risk.Value, prediction, factors);
            await update.ExecuteNonQueryAsync(ct);
        }

        var levelChanged = !string.Equals(oldLevel, risk.Value.Level, StringComparison.OrdinalIgnoreCase);
        if (levelChanged)
        {
            await using var history = new NpgsqlCommand("insert into alert_level_history(alert_id,from_level,to_level,changed_at) values(@id,@from,@to,@at)", connection, transaction);
            history.Parameters.AddWithValue("id", alertId);
            history.Parameters.AddWithValue("from", (object?)oldLevel ?? DBNull.Value);
            history.Parameters.AddWithValue("to", risk.Value.Level);
            history.Parameters.AddWithValue("at", prediction.CalculatedAt);
            await history.ExecuteNonQueryAsync(ct);
        }

        await transaction.CommitAsync(ct);
        return alertId;
    }

    public async Task<Guid> PublishAsync(
        Guid calculationId,
        ModelDemoScenario scenario,
        MlPrediction prediction,
        CancellationToken cancellationToken)
    {
        var risk = SelectRisk(prediction) ?? throw new InvalidOperationException("prediction threshold was not exceeded");
        var objectId = $"model-demo-{scenario.Id}";
        try
        {
            await using var connection = await dataSource.OpenConnectionAsync(cancellationToken);
            await using var transaction = await connection.BeginTransactionAsync(cancellationToken);

            await using (var existing = new NpgsqlCommand(
                "select id from risk_alerts where demo_calculation_id=@calculationId", connection, transaction))
            {
                existing.Parameters.AddWithValue("calculationId", calculationId);
                var value = await existing.ExecuteScalarAsync(cancellationToken);
                if (value is Guid existingId)
                {
                    await transaction.CommitAsync(cancellationToken);
                    return existingId;
                }
            }

            await using (var upsertObject = new NpgsqlCommand("""
                insert into infrastructure_objects(id,name,district,is_demo)
                values(@id,@name,@district,true)
                on conflict(id) do update set name=excluded.name,district=excluded.district
                where infrastructure_objects.is_demo
                """, connection, transaction))
            {
                upsertObject.Parameters.AddWithValue("id", objectId);
                upsertObject.Parameters.AddWithValue("name", scenario.ObjectName);
                upsertObject.Parameters.AddWithValue("district", scenario.District);
                await upsertObject.ExecuteNonQueryAsync(cancellationToken);
            }

            foreach (var sensor in scenario.Sensors)
            {
                await using var channel = new NpgsqlCommand("""
                    insert into data_channels(id,object_id,sensor_type,name,picket_raw,picket_sort_key,
                      display_value,display_state,age_source,metadata_source,is_demo)
                    values(@id,@objectId,@type,@name,@picket,@sort,@value,@state,'imported','model_demo',true)
                    on conflict(id) do update set sensor_type=excluded.sensor_type,name=excluded.name,
                      picket_raw=excluded.picket_raw,picket_sort_key=excluded.picket_sort_key,
                      display_value=excluded.display_value,display_state=excluded.display_state
                    where data_channels.is_demo
                    """, connection, transaction);
                channel.Parameters.AddWithValue("id", $"model-demo-{scenario.Id}-{sensor.Id}");
                channel.Parameters.AddWithValue("objectId", objectId);
                channel.Parameters.AddWithValue("type", sensor.SensorType);
                channel.Parameters.AddWithValue("name", sensor.Name);
                channel.Parameters.AddWithValue("picket", (object?)sensor.Picket ?? DBNull.Value);
                channel.Parameters.AddWithValue("sort", (object?)ParsePicket(sensor.Picket) ?? DBNull.Value);
                channel.Parameters.AddWithValue("value", sensor.Value);
                channel.Parameters.AddWithValue("state", sensor.State);
                await channel.ExecuteNonQueryAsync(cancellationToken);
            }

            var factors = JsonSerializer.Serialize(prediction.Factors, JsonOptions);
            await using (var insertPrediction = new NpgsqlCommand("""
                insert into risk_predictions(id,object_id,model_version,calculated_at,p_now,p_6h,p_12h,p_24h,
                  factors,is_demo,demo_calculation_id)
                values(@id,@objectId,@model,@at,@pNow,@p6,@p12,@p24,@factors::jsonb,true,@calculationId)
                """, connection, transaction))
            {
                insertPrediction.Parameters.AddWithValue("id", Guid.NewGuid());
                AddDemoPredictionParameters(insertPrediction, calculationId, objectId, prediction, factors);
                await insertPrediction.ExecuteNonQueryAsync(cancellationToken);
            }

            await using (var supersede = new NpgsqlCommand(
                "update risk_alerts set current=false where object_id=@objectId and is_demo and current", connection, transaction))
            {
                supersede.Parameters.AddWithValue("objectId", objectId);
                await supersede.ExecuteNonQueryAsync(cancellationToken);
            }

            var alertId = Guid.NewGuid();
            var episodeId = $"DEMO-{calculationId:N}";
            await using (var insertAlert = new NpgsqlCommand("""
                insert into risk_alerts(id,episode_id,object_id,level,horizon,probability,p_now,p_6h,p_12h,p_24h,
                  calculated_at,model_version,stale,factors,recommendation,alert_kind,context,current,is_demo,demo_calculation_id)
                values(@id,@episode,@objectId,@level,@horizon,@prob,@pNow,@p6,@p12,@p24,@at,@model,false,
                  @factors::jsonb,'Проверить показания датчиков и состояние объекта','fire',@context,true,true,@calculationId)
                """, connection, transaction))
            {
                AddAlertParameters(insertAlert, alertId, episodeId, objectId, risk, prediction, factors);
                insertAlert.Parameters.AddWithValue("calculationId", calculationId);
                insertAlert.Parameters.AddWithValue("context", $"Отложенный срез {scenario.SourceTimestamp:dd.MM.yyyy HH:mm}; исходный объект {scenario.ObjectId}; {scenario.DangerousSection}");
                await insertAlert.ExecuteNonQueryAsync(cancellationToken);
            }

            await using (var history = new NpgsqlCommand(
                "insert into alert_level_history(alert_id,from_level,to_level,changed_at) values(@id,null,@to,@at)", connection, transaction))
            {
                history.Parameters.AddWithValue("id", alertId);
                history.Parameters.AddWithValue("to", risk.Level);
                history.Parameters.AddWithValue("at", prediction.CalculatedAt);
                await history.ExecuteNonQueryAsync(cancellationToken);
            }

            await transaction.CommitAsync(cancellationToken);
            return alertId;
        }
        catch (PostgresException exception) when (exception.SqlState == PostgresErrorCodes.UniqueViolation)
        {
            await using var command = dataSource.CreateCommand(
                "select id from risk_alerts where demo_calculation_id=@calculationId");
            command.Parameters.AddWithValue("calculationId", calculationId);
            if (await command.ExecuteScalarAsync(cancellationToken) is Guid existingId) return existingId;
            throw;
        }
    }

    public async Task DeleteResultsAsync(CancellationToken cancellationToken)
    {
        await using var connection = await dataSource.OpenConnectionAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);
        await using var command = new NpgsqlCommand("""
            delete from sms_notifications where request_id in (
              select r.id from maintenance_requests r join risk_alerts a on a.id=r.alert_id where a.is_demo);
            delete from request_comments where request_id in (
              select r.id from maintenance_requests r join risk_alerts a on a.id=r.alert_id where a.is_demo);
            delete from maintenance_requests where alert_id in (select id from risk_alerts where is_demo);
            delete from dispatcher_decisions where alert_id in (select id from risk_alerts where is_demo);
            delete from alert_level_history where alert_id in (select id from risk_alerts where is_demo);
            delete from risk_alerts where is_demo;
            delete from risk_predictions where is_demo;
            delete from data_channels where is_demo;
            delete from infrastructure_objects where is_demo;
            """, connection, transaction);
        await command.ExecuteNonQueryAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
    }

    private static (string Level, string Horizon, double Probability)? SelectRisk(MlPrediction p)
    {
        bool Decision(string key) => p.Decisions.TryGetValue(key, out var value) && value;
        if (Decision("now")) return ("black", "now", p.PNow);
        if (Decision("6h")) return ("red", "6h", p.P6h);
        if (Decision("12h")) return ("yellow", "12h", p.P12h);
        if (Decision("24h")) return ("green", "24h", p.P24h);
        return null;
    }

    private static void AddDemoPredictionParameters(
        NpgsqlCommand command,
        Guid calculationId,
        string objectId,
        MlPrediction prediction,
        string factors)
    {
        command.Parameters.AddWithValue("calculationId", calculationId);
        command.Parameters.AddWithValue("objectId", objectId);
        command.Parameters.AddWithValue("model", prediction.ModelVersion);
        command.Parameters.AddWithValue("at", prediction.CalculatedAt);
        command.Parameters.AddWithValue("pNow", prediction.PNow);
        command.Parameters.AddWithValue("p6", prediction.P6h);
        command.Parameters.AddWithValue("p12", prediction.P12h);
        command.Parameters.AddWithValue("p24", prediction.P24h);
        command.Parameters.AddWithValue("factors", factors);
    }

    private static double? ParsePicket(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        var normalized = value.Replace("ПК", "", StringComparison.OrdinalIgnoreCase).Trim().Replace('+', '.');
        return double.TryParse(normalized, NumberStyles.Float, CultureInfo.InvariantCulture, out var result) ? result : null;
    }

    private static void AddAlertParameters(NpgsqlCommand command, Guid id, string episode, string objectId,
        (string Level, string Horizon, double Probability) risk, MlPrediction p, string factors)
    {
        command.Parameters.AddWithValue("id", id); command.Parameters.AddWithValue("episode", episode);
        command.Parameters.AddWithValue("objectId", objectId); command.Parameters.AddWithValue("level", risk.Level);
        command.Parameters.AddWithValue("horizon", risk.Horizon); command.Parameters.AddWithValue("prob", risk.Probability);
        command.Parameters.AddWithValue("pNow", p.PNow); command.Parameters.AddWithValue("p6", p.P6h);
        command.Parameters.AddWithValue("p12", p.P12h); command.Parameters.AddWithValue("p24", p.P24h);
        command.Parameters.AddWithValue("at", p.CalculatedAt); command.Parameters.AddWithValue("model", p.ModelVersion);
        command.Parameters.AddWithValue("factors", factors);
    }

    private async Task<JsonElement> JsonAsync(string sql, CancellationToken ct, params NpgsqlParameter[] parameters)
    {
        await using var command = dataSource.CreateCommand(sql);
        command.Parameters.AddRange(parameters);
        var json = Convert.ToString(await command.ExecuteScalarAsync(ct)) ?? "null";
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private static string StatusName(MaintenanceStatus status) => status switch
    {
        MaintenanceStatus.InProgress => "in_progress",
        _ => status.ToString().ToLowerInvariant()
    };

    private static MaintenanceStatus ParseStatus(string value) => value switch
    {
        "under_review" or "scheduled" => MaintenanceStatus.InProgress,
        "in_progress" => MaintenanceStatus.InProgress,
        _ => Enum.Parse<MaintenanceStatus>(value, true)
    };

    private static string EnumName<T>(T value) where T : struct, Enum =>
        string.Concat(value.ToString().Select((character, index) => index > 0 && char.IsUpper(character) ? $"_{char.ToLowerInvariant(character)}" : char.ToLowerInvariant(character).ToString()));

    private static async Task<string> NextPublicRequestIdAsync(NpgsqlConnection connection, NpgsqlTransaction transaction, CancellationToken ct)
    {
        for (var attempt = 0; attempt < 100; attempt++)
        {
            var candidate = RandomNumberGenerator.GetInt32(0, 100000).ToString("D5");
            await using var command = new NpgsqlCommand("select not exists(select 1 from maintenance_requests where public_id=@publicId)", connection, transaction);
            command.Parameters.AddWithValue("publicId", candidate);
            if (Convert.ToBoolean(await command.ExecuteScalarAsync(ct))) return candidate;
        }
        throw new InvalidOperationException("Could not allocate a public request id");
    }
}
