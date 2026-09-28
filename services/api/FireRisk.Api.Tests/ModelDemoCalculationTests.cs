using Microsoft.Extensions.Caching.Memory;

namespace FireRisk.Api.Tests;

public sealed class ModelDemoCalculationTests
{
    [Fact]
    public async Task Prediction_forwards_every_feature_and_caches_fresh_result()
    {
        var gateway = new FakeGateway(Prediction());
        var clock = new FakeTimeProvider(new DateTimeOffset(2026, 9, 29, 9, 0, 0, TimeSpan.Zero));
        var cache = new ModelDemoCalculationCache(new MemoryCache(new MemoryCacheOptions()), clock);
        var service = new ModelDemoService(Catalog(), gateway, cache);

        var response = await service.PredictAsync("held-out-01", CancellationToken.None);

        Assert.NotEqual(Guid.Empty, response.CalculationId);
        Assert.Equal("held-out-01", response.Scenario.Id);
        Assert.Equal(157, gateway.LastRequest!.Features.Count);
        Assert.Equal(5, gateway.LastRequest.TopK);
        Assert.Equal(Prediction().CalculatedAt, response.Prediction.CalculatedAt);
        Assert.Equal(response.Prediction, cache.Get(response.CalculationId).Prediction);
    }

    [Fact]
    public async Task Listing_and_unknown_ids_do_not_call_inference()
    {
        var gateway = new FakeGateway(Prediction());
        var service = new ModelDemoService(Catalog(), gateway, Cache());

        Assert.Equal(24, service.List().Count);
        await Assert.ThrowsAsync<KeyNotFoundException>(() => service.PredictAsync("missing", CancellationToken.None));
        Assert.Equal(0, gateway.CallCount);
    }

    [Fact]
    public async Task Failed_inference_does_not_create_a_calculation()
    {
        var gateway = new FakeGateway(new HttpRequestException("offline"));
        var cache = Cache();
        var service = new ModelDemoService(Catalog(), gateway, cache);

        await Assert.ThrowsAsync<HttpRequestException>(() => service.PredictAsync("held-out-01", CancellationToken.None));

        Assert.Empty(cache.ActiveIds);
    }

    [Fact]
    public void Calculation_expires_at_exactly_30_minutes()
    {
        var clock = new FakeTimeProvider(new DateTimeOffset(2026, 9, 29, 9, 0, 0, TimeSpan.Zero));
        var cache = new ModelDemoCalculationCache(new MemoryCache(new MemoryCacheOptions()), clock);
        var created = cache.Create("held-out-01", Prediction());

        clock.Advance(TimeSpan.FromMinutes(29) + TimeSpan.FromSeconds(59));
        Assert.Equal(created.Id, cache.Get(created.Id).Id);

        clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Throws<KeyNotFoundException>(() => cache.Get(created.Id));
        Assert.Empty(cache.ActiveIds);
    }

    private static ModelDemoScenarioCatalog Catalog() => new(
        Path.Combine(AppContext.BaseDirectory, "Data", "model-demo-scenarios.json"));

    private static ModelDemoCalculationCache Cache() => new(
        new MemoryCache(new MemoryCacheOptions()),
        new FakeTimeProvider(new DateTimeOffset(2026, 9, 29, 9, 0, 0, TimeSpan.Zero)));

    private static MlPrediction Prediction() => new(
        "model-v1",
        new DateTimeOffset(2026, 9, 29, 9, 1, 0, TimeSpan.Zero),
        0.1,
        0.4,
        0.6,
        0.8,
        new Dictionary<string, bool> { ["now"] = false, ["6h"] = true, ["12h"] = true, ["24h"] = true },
        []);

    private sealed class FakeGateway : IMlGateway
    {
        private readonly MlPrediction? prediction;
        private readonly Exception? exception;

        public FakeGateway(MlPrediction prediction) => this.prediction = prediction;
        public FakeGateway(Exception exception) => this.exception = exception;

        public int CallCount { get; private set; }
        public PredictRequest? LastRequest { get; private set; }

        public Task<object?> GetModelAsync(CancellationToken cancellationToken) => Task.FromResult<object?>(null);

        public Task<MlPrediction> PredictAsync(PredictRequest request, CancellationToken cancellationToken)
        {
            CallCount++;
            LastRequest = request;
            return exception is null ? Task.FromResult(prediction!) : Task.FromException<MlPrediction>(exception);
        }
    }

    private sealed class FakeTimeProvider(DateTimeOffset now) : TimeProvider
    {
        private DateTimeOffset current = now;
        public override DateTimeOffset GetUtcNow() => current;
        public void Advance(TimeSpan amount) => current += amount;
    }
}
