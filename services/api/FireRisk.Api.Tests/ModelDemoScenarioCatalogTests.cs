using System.Text.Json;

namespace FireRisk.Api.Tests;

public sealed class ModelDemoScenarioCatalogTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), $"model-demo-{Guid.NewGuid():N}");

    [Fact]
    public void Catalog_loads_exactly_24_ordered_held_out_scenarios()
    {
        var catalog = new ModelDemoScenarioCatalog(WriteCatalog());

        var summaries = catalog.List();

        Assert.Equal(24, summaries.Count);
        Assert.Equal(Enumerable.Range(1, 24).Select(index => $"scenario-{index:D2}"), summaries.Select(item => item.Id));
        Assert.Equal(24, summaries.Select(item => item.Id).Distinct().Count());
        Assert.All(summaries, item =>
        {
            Assert.Equal(2026, item.SourceTimestamp.Year);
            Assert.False(string.IsNullOrWhiteSpace(item.ObjectName));
            Assert.False(string.IsNullOrWhiteSpace(item.District));
            Assert.NotEmpty(item.Sensors);
        });
        Assert.Null(typeof(ModelDemoScenarioSummary).GetProperty("Features"));
        Assert.Null(typeof(ModelDemoScenarioSummary).GetProperty("ExpectedProbability"));
    }

    [Fact]
    public void Catalog_requires_the_exact_feature_schema_and_matching_calendar()
    {
        var catalog = new ModelDemoScenarioCatalog(WriteCatalog());
        var scenario = catalog.Get("scenario-01");

        Assert.Equal(new[] { "hour", "weekday", "month" }, scenario.Features.Keys);
        Assert.Equal(12d, scenario.Features["hour"]);
        Assert.Equal(2d, scenario.Features["weekday"]);
        Assert.Equal(9d, scenario.Features["month"]);
        Assert.Throws<KeyNotFoundException>(() => catalog.Get("missing"));
    }

    [Fact]
    public void Summary_exposes_only_curated_readable_inputs()
    {
        var scenario = new ModelDemoScenario(
            "scenario-01",
            new DateTimeOffset(2026, 9, 29, 9, 0, 0, TimeSpan.Zero),
            "42",
            "Объект 42",
            "САО",
            "ПК 1+00",
            [new ModelDemoSensor("sensor-1", "Температура", "heat", "ПК 1+00", "61 °C", "warning")],
            new Dictionary<string, double?>
            {
                ["event_count_30m"] = 17,
                ["alarm_count_5m"] = 3,
                ["malfunction_count_5m"] = 1,
                ["smoke_heat_5m"] = 1,
                ["gas_alarm_count_5m"] = 0,
                ["stale_channel_count"] = null,
            });

        var summary = scenario.ToSummary();

        Assert.Equal(
            [
                new ModelDemoInput("События за 30 минут", "17"),
                new ModelDemoInput("Тревоги за 5 минут", "3"),
                new ModelDemoInput("Неисправности за 5 минут", "1"),
                new ModelDemoInput("Дым или нагрев", "Есть"),
                new ModelDemoInput("Газовые тревоги за 5 минут", "0"),
                new ModelDemoInput("Неактуальные каналы", "Нет данных"),
            ],
            summary.Inputs);
        Assert.Null(typeof(ModelDemoScenarioSummary).GetProperty("Features"));
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(true, true)]
    public void Catalog_rejects_missing_or_extra_features(bool includeMonth, bool includeExtra)
    {
        Assert.Throws<InvalidDataException>(() => new ModelDemoScenarioCatalog(WriteCatalog(includeMonth, includeExtra)));
    }

    [Fact]
    public void Catalog_rejects_calendar_values_that_disagree_with_moscow_time()
    {
        Assert.Throws<InvalidDataException>(() => new ModelDemoScenarioCatalog(WriteCatalog(hour: 9)));
    }

    [Fact]
    public void Bundled_catalog_is_complete_and_loadable()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Data", "model-demo-scenarios.json");

        var catalog = new ModelDemoScenarioCatalog(path);

        Assert.Equal(24, catalog.List().Count);
        Assert.All(catalog.List(), item => Assert.Equal(2026, item.SourceTimestamp.Year));
    }

    private string WriteCatalog(bool includeMonth = true, bool includeExtra = false, int hour = 12)
    {
        Directory.CreateDirectory(directory);
        var scenarios = Enumerable.Range(1, 24).Select(index =>
        {
            var features = new Dictionary<string, double?>
            {
                ["hour"] = hour,
                ["weekday"] = 2,
            };
            if (includeMonth) features["month"] = 9;
            if (includeExtra) features["unexpected"] = 1;
            return new
            {
                id = $"scenario-{index:D2}",
                sourceTimestamp = "2026-09-29T09:00:00Z",
                objectId = $"source-object-{index:D2}",
                objectName = $"Тестовый объект {index:D2}",
                district = "САО",
                dangerousSection = "ПК 12+50",
                sensors = new[]
                {
                    new { id = $"sensor-{index:D2}", name = "Температура", sensorType = "Температура", picket = "12+50", value = "42 °C", state = "normal" }
                },
                features,
            };
        });
        var payload = new { featureNames = new[] { "hour", "weekday", "month" }, scenarios };
        var path = Path.Combine(directory, $"catalog-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(payload));
        return path;
    }

    public void Dispose()
    {
        if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
    }
}
