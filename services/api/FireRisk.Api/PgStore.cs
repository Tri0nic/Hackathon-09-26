using System.Text.Json;
using FireRisk.Api.Domain;
using Npgsql;

namespace FireRisk.Api;

public sealed class PgStore(NpgsqlDataSource dataSource, IConfiguration configuration)
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly TimeSpan _smsCooldown = TimeSpan.FromMinutes(configuration.GetValue("Sms:CooldownMinutes", 30));

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
            a.calculated_at "calculatedAt", a.model_version "modelVersion", a.stale, a.current,
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
          'calculatedAt', a.calculated_at, 'modelVersion', a.model_version, 'stale', a.stale,
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

    public async Task<Guid> AddRequestAsync(Guid alertId, string? recommendation, CancellationToken ct)
    {
        var id = Guid.NewGuid();
        await using var command = dataSource.CreateCommand("""
            insert into maintenance_requests(id, alert_id, object_id, picket, factors, recommendation, status, created_at, updated_at)
            select @id, a.id, a.object_id,
              (select min(picket_raw) from data_channels where object_id=a.object_id and picket_sort_key is not null),
              a.factors, coalesce(@recommendation, a.recommendation), 'new', now(), now()
            from risk_alerts a where a.id=@alertId
            """);
        command.Parameters.AddWithValue("id", id);
        command.Parameters.AddWithValue("alertId", alertId);
        command.Parameters.AddWithValue("recommendation", (object?)recommendation ?? DBNull.Value);
        if (await command.ExecuteNonQueryAsync(ct) == 0) throw new KeyNotFoundException("Alert not found");
        return id;
    }

    public Task<JsonElement> GetRequestsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x."createdAt" desc), '[]'::json)::text from (
          select r.id, r.alert_id "alertId", r.object_id "objectId", o.name "objectName", r.picket,
            r.factors, r.recommendation, r.status, r.created_at "createdAt", r.updated_at "updatedAt"
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
        return true;
    }

    public Task<JsonElement> GetSmsAsync(CancellationToken ct) => JsonAsync("""
        select coalesce(json_agg(row_to_json(x) order by x."sentAt" desc), '[]'::json)::text from (
          select id, episode_id "episodeId", alert_level "alertLevel", recipient_id "recipientId",
            role, sent_at "sentAt", content, status from sms_notifications
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

        await DispatchSmsAsync(connection, transaction, episodeId, risk.Value.Level, prediction.CalculatedAt, levelChanged, ct);
        await transaction.CommitAsync(ct);
        return alertId;
    }

    private async Task DispatchSmsAsync(NpgsqlConnection connection, NpgsqlTransaction transaction, string episodeId, string levelName, DateTimeOffset now, bool levelChanged, CancellationToken ct)
    {
        var level = Enum.Parse<AlertLevel>(levelName, true);
        foreach (var role in Enum.GetValues<RecipientRole>().Where(r => r != RecipientRole.None && SmsPolicy.Recipients(level).HasFlag(r)))
        {
            var recipient = role.ToString();
            await using var last = new NpgsqlCommand("""
                select max(sent_at) from sms_notifications
                where episode_id=@episode and alert_level=@level and recipient_id=@recipient
                """, connection, transaction);
            last.Parameters.AddWithValue("episode", episodeId);
            last.Parameters.AddWithValue("level", levelName);
            last.Parameters.AddWithValue("recipient", recipient);
            var value = await last.ExecuteScalarAsync(ct);
            var lastSent = value switch
            {
                DateTimeOffset timestamp => timestamp,
                DateTime timestamp => new DateTimeOffset(timestamp),
                _ => (DateTimeOffset?)null
            };
            if (!SmsPolicy.CanSend(lastSent, now, _smsCooldown, levelChanged)) continue;

            await using var insert = new NpgsqlCommand("""
                insert into sms_notifications(id,episode_id,alert_level,recipient_id,role,sent_at,content,status)
                values(@id,@episode,@level,@recipient,@role,@at,@content,'delivered')
                """, connection, transaction);
            insert.Parameters.AddWithValue("id", Guid.NewGuid());
            insert.Parameters.AddWithValue("episode", episodeId);
            insert.Parameters.AddWithValue("level", levelName);
            insert.Parameters.AddWithValue("recipient", recipient);
            insert.Parameters.AddWithValue("role", recipient);
            insert.Parameters.AddWithValue("at", now);
            insert.Parameters.AddWithValue("content", $"Пожарный риск {levelName}: эпизод {episodeId}");
            await insert.ExecuteNonQueryAsync(ct);
        }
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
        MaintenanceStatus.UnderReview => "under_review",
        MaintenanceStatus.InProgress => "in_progress",
        _ => status.ToString().ToLowerInvariant()
    };

    private static MaintenanceStatus ParseStatus(string value) => value switch
    {
        "under_review" => MaintenanceStatus.UnderReview,
        "in_progress" => MaintenanceStatus.InProgress,
        _ => Enum.Parse<MaintenanceStatus>(value, true)
    };
}
