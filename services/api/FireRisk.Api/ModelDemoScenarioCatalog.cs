using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;

namespace FireRisk.Api;

public sealed record ModelDemoSensor(
    string Id,
    string Name,
    string SensorType,
    string? Picket,
    string Value,
    string State);

public sealed record ModelDemoInput(string Label, string Value);

public sealed record ModelDemoScenarioSummary(
    string Id,
    DateTimeOffset SourceTimestamp,
    string ObjectId,
    string ObjectName,
    string District,
    string DangerousSection,
    IReadOnlyList<ModelDemoSensor> Sensors,
    IReadOnlyList<ModelDemoInput> Inputs);

public sealed record ModelDemoScenario(
    string Id,
    DateTimeOffset SourceTimestamp,
    string ObjectId,
    string ObjectName,
    string District,
    string DangerousSection,
    IReadOnlyList<ModelDemoSensor> Sensors,
    IReadOnlyDictionary<string, double?> Features)
{
    public ModelDemoScenarioSummary ToSummary() =>
        new(Id, SourceTimestamp, ObjectId, ObjectName, District, DangerousSection, Sensors, BuildInputs());

    private IReadOnlyList<ModelDemoInput> BuildInputs() =>
    [
        NumberInput("События за 30 минут", "event_count_30m"),
        NumberInput("Тревоги за 5 минут", "alarm_count_5m"),
        NumberInput("Неисправности за 5 минут", "malfunction_count_5m"),
        BooleanInput("Дым или нагрев", "smoke_heat_5m"),
        NumberInput("Газовые тревоги за 5 минут", "gas_alarm_count_5m"),
        NumberInput("Неактуальные каналы", "stale_channel_count"),
    ];

    private ModelDemoInput NumberInput(string label, string feature) =>
        new(label, Features.TryGetValue(feature, out var value) && value.HasValue
            ? value.Value.ToString("0.##", CultureInfo.InvariantCulture)
            : "Нет данных");

    private ModelDemoInput BooleanInput(string label, string feature) =>
        new(label, Features.TryGetValue(feature, out var value) && value.HasValue
            ? value.Value > 0 ? "Есть" : "Нет"
            : "Нет данных");
}

public sealed class ModelDemoScenarioCatalog
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private static readonly TimeZoneInfo MoscowTimeZone = TimeZoneInfo.FindSystemTimeZoneById("Europe/Moscow");
    private readonly IReadOnlyList<ModelDemoScenario> scenarios;
    private readonly IReadOnlyDictionary<string, ModelDemoScenario> byId;

    public ModelDemoScenarioCatalog(string path)
    {
        try
        {
            var document = JsonSerializer.Deserialize<CatalogDocument>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("model demo catalog is empty");
            Validate(document);
            scenarios = Array.AsReadOnly(document.Scenarios);
            byId = new ReadOnlyDictionary<string, ModelDemoScenario>(
                document.Scenarios.ToDictionary(item => item.Id, StringComparer.Ordinal));
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or JsonException or ArgumentException)
        {
            throw new InvalidDataException("model demo catalog is invalid", exception);
        }
    }

    public IReadOnlyList<ModelDemoScenarioSummary> List() => scenarios.Select(item => item.ToSummary()).ToArray();

    public ModelDemoScenario Get(string id) => byId.TryGetValue(id, out var scenario)
        ? scenario
        : throw new KeyNotFoundException("scenario not found");

    private static void Validate(CatalogDocument document)
    {
        if (document.FeatureNames.Length == 0 || document.FeatureNames.Distinct(StringComparer.Ordinal).Count() != document.FeatureNames.Length)
            throw new InvalidDataException("feature schema must contain unique names");
        if (document.Scenarios.Length != 24)
            throw new InvalidDataException("catalog must contain exactly 24 scenarios");
        if (document.Scenarios.Select(item => item.Id).Distinct(StringComparer.Ordinal).Count() != document.Scenarios.Length)
            throw new InvalidDataException("scenario IDs must be unique");

        var expectedFeatures = document.FeatureNames.ToHashSet(StringComparer.Ordinal);
        foreach (var scenario in document.Scenarios)
        {
            if (string.IsNullOrWhiteSpace(scenario.Id) || string.IsNullOrWhiteSpace(scenario.ObjectId) ||
                string.IsNullOrWhiteSpace(scenario.ObjectName) || string.IsNullOrWhiteSpace(scenario.District) || scenario.Sensors.Count == 0)
                throw new InvalidDataException("scenario context is incomplete");
            if (scenario.SourceTimestamp.Year != 2026)
                throw new InvalidDataException("scenario is outside the held-out 2026 period");
            if (!expectedFeatures.SetEquals(scenario.Features.Keys))
                throw new InvalidDataException("scenario feature set does not match the schema");

            var local = TimeZoneInfo.ConvertTime(scenario.SourceTimestamp, MoscowTimeZone);
            var isoWeekday = local.DayOfWeek == DayOfWeek.Sunday ? 7 : (int)local.DayOfWeek;
            if (!CalendarEquals(scenario.Features, "hour", local.Hour) ||
                !CalendarEquals(scenario.Features, "weekday", isoWeekday) ||
                !CalendarEquals(scenario.Features, "month", local.Month))
                throw new InvalidDataException("scenario calendar features do not match source timestamp");
        }
    }

    private static bool CalendarEquals(IReadOnlyDictionary<string, double?> features, string key, int expected) =>
        features.TryGetValue(key, out var value) && value == expected;

    private sealed record CatalogDocument(string[] FeatureNames, ModelDemoScenario[] Scenarios);
}
