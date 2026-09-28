using System.Text.Json;
using System.Text.Json.Serialization;
using FireRisk.Api;
using FireRisk.Api.Domain;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);
builder.Services.ConfigureHttpJsonOptions(options =>
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower)));

var connectionString = builder.Configuration.GetConnectionString("Postgres")
    ?? throw new InvalidOperationException("ConnectionStrings:Postgres is required");
builder.Services.AddSingleton(_ => NpgsqlDataSource.Create(connectionString));
builder.Services.AddSingleton<PgStore>();
builder.Services.AddHttpClient<IMlGateway, MlClient>(client =>
{
    client.BaseAddress = new Uri(builder.Configuration["Ml:BaseUrl"] ?? "http://localhost:8000");
    client.Timeout = TimeSpan.FromSeconds(builder.Configuration.GetValue("Ml:TimeoutSeconds", 10));
});
builder.Services.AddMemoryCache();
builder.Services.AddSingleton<TimeProvider>(TimeProvider.System);
builder.Services.AddSingleton<ModelDemoCalculationCache>();
builder.Services.AddSingleton(serviceProvider =>
{
    var environment = serviceProvider.GetRequiredService<IHostEnvironment>();
    return new ModelDemoScenarioCatalog(Path.Combine(environment.ContentRootPath, "Data", "model-demo-scenarios.json"));
});
builder.Services.AddScoped<ModelDemoService>();

var app = builder.Build();

if (builder.Configuration.GetValue("Database:MigrateOnStart", true))
    await app.Services.GetRequiredService<PgStore>().MigrateAsync();

app.MapGet("/health", async (PgStore store, CancellationToken ct) =>
    await store.IsHealthyAsync(ct) ? Results.Ok(new { status = "ok" }) : Results.StatusCode(503));

app.MapGet("/api/dashboard", (PgStore store, CancellationToken ct) => store.GetDashboardAsync(ct));
app.MapGet("/api/objects", (PgStore store, CancellationToken ct) => store.GetObjectsAsync(ct));
app.MapGet("/api/objects/{id}", async (string id, PgStore store, CancellationToken ct) =>
{
    var value = await store.GetObjectAsync(id, ct);
    return value.ValueKind == JsonValueKind.Null ? Results.NotFound() : Results.Ok(value);
});
app.MapGet("/api/objects/{id}/pickets", (string id, PgStore store, CancellationToken ct) => store.GetPicketsAsync(id, ct));

app.MapGet("/api/alerts", (PgStore store, CancellationToken ct) => store.GetAlertsAsync(ct));
app.MapGet("/api/alerts/{id:guid}", async (Guid id, PgStore store, CancellationToken ct) =>
{
    var value = await store.GetAlertAsync(id, ct);
    return value.ValueKind == JsonValueKind.Null ? Results.NotFound() : Results.Ok(value);
});

var decisions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
{
    "confirmed_fire", "smoke_without_fire", "false_alarm",
    "sensor_malfunction", "maintenance", "unknown"
};
app.MapPost("/api/alerts/{id:guid}/decision", async (Guid id, DecisionRequest request, PgStore store, CancellationToken ct) =>
{
    if (!decisions.Contains(request.Decision)) return Results.BadRequest(new { error = "unknown decision" });
    try { return Results.Created($"/api/alerts/{id}", new { id = await store.AddDecisionAsync(id, request.Decision, request.Comment, ct) }); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});

app.MapPost("/api/alerts/{id:guid}/requests", async (Guid id, CreateMaintenanceRequest request, PgStore store, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(request.Description)) return Results.BadRequest(new { error = "description is required" });
    try { return Results.Created("/api/requests", await store.AddRequestAsync(id, request, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
    catch (InvalidOperationException exception) { return Results.BadRequest(new { error = exception.Message }); }
});
app.MapGet("/api/requests", (PgStore store, CancellationToken ct) => store.GetRequestsAsync(ct));
app.MapPatch("/api/requests/{id:guid}/status", async (Guid id, ChangeRequestStatus request, PgStore store, CancellationToken ct) =>
{
    try { return await store.ChangeRequestStatusAsync(id, request.Status, ct) ? Results.NoContent() : Results.NotFound(); }
    catch (InvalidOperationException exception) { return Results.BadRequest(new { error = exception.Message }); }
});
app.MapPost("/api/requests/{id:guid}/claim", async (Guid id, ClaimMaintenanceRequest request, PgStore store, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(request.EmployeeId) || string.IsNullOrWhiteSpace(request.EmployeeName))
        return Results.BadRequest(new { error = "employee is required" });
    return await store.ClaimRequestAsync(id, request.EmployeeId, request.EmployeeName, request.ExecutorGroup, ct) switch
    {
        ClaimRequestResult.Claimed => Results.NoContent(),
        ClaimRequestResult.AlreadyAssigned => Results.Conflict(new { error = "request already assigned" }),
        _ => Results.NotFound()
    };
});
app.MapPost("/api/requests/{id:guid}/executor-action", async (Guid id, ExecuteRequestAction request, PgStore store, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(request.EmployeeId) || string.IsNullOrWhiteSpace(request.EmployeeName))
        return Results.BadRequest(new { error = "employee is required" });
    return await store.ExecuteRequestActionAsync(id, request, ct) switch
    {
        ExecutorActionResult.Updated => Results.NoContent(),
        ExecutorActionResult.CommentRequired => Results.BadRequest(new { error = "cancellation comment is required" }),
        ExecutorActionResult.Forbidden => Results.StatusCode(403),
        _ => Results.NotFound()
    };
});
app.MapGet("/api/sms", (PgStore store, CancellationToken ct) => store.GetSmsAsync(ct));

app.MapPost("/api/objects/{id}/predict", async (string id, PredictRequest request, IMlGateway ml, PgStore store, CancellationToken ct) =>
{
    try
    {
        var prediction = await ml.PredictAsync(request, ct);
        var alertId = await store.SavePredictionAsync(id, prediction, ct);
        return Results.Ok(new { prediction, alertId });
    }
    catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
    {
        var last = await store.GetLastPredictionAsync(id, ct);
        if (last is null) return Results.StatusCode(503);
        await store.MarkCurrentAlertStaleAsync(id, ct);
        return Results.Ok(new { prediction = PredictionFallback.FromFailure(last), alertId = (Guid?)null });
    }
});

app.MapGet("/api/model/metrics", async (IMlGateway ml, CancellationToken ct) =>
{
    try { return Results.Ok(await ml.GetModelAsync(ct)); }
    catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException) { return Results.StatusCode(503); }
});

app.MapGet("/api/model-demo/scenarios", (ModelDemoService service) => Results.Ok(service.List()));
app.MapPost("/api/model-demo/predict", async (ModelDemoPredictionRequest request, ModelDemoService service, CancellationToken ct) =>
{
    try { return Results.Ok(await service.PredictAsync(request.ScenarioId, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(new { error = "scenario not found" }); }
    catch (Exception exception) when (exception is HttpRequestException or TaskCanceledException)
    {
        return Results.StatusCode(503);
    }
});

app.Run();

public partial class Program;
