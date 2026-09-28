using Microsoft.Extensions.Caching.Memory;

namespace FireRisk.Api.Tests;

public sealed class ModelDemoPublicationTests
{
    [Fact]
    public async Task Safe_or_unknown_calculation_cannot_be_published()
    {
        var (service, cache, store) = Service();
        var safe = cache.Create("held-out-01", Prediction(dangerous: false));

        await Assert.ThrowsAsync<InvalidOperationException>(() => service.PublishAsync(safe.Id, CancellationToken.None));
        await Assert.ThrowsAsync<KeyNotFoundException>(() => service.PublishAsync(Guid.NewGuid(), CancellationToken.None));
        Assert.Equal(0, store.PublishCalls);
    }

    [Fact]
    public async Task Sequential_and_concurrent_publication_creates_one_alert()
    {
        var (service, cache, store) = Service(delayPublication: true);
        var calculation = cache.Create("held-out-01", Prediction(dangerous: true));

        var first = service.PublishAsync(calculation.Id, CancellationToken.None);
        var second = service.PublishAsync(calculation.Id, CancellationToken.None);
        var results = await Task.WhenAll(first, second);
        var replay = await service.PublishAsync(calculation.Id, CancellationToken.None);

        Assert.All(results, result => Assert.Equal(store.AlertId, result.AlertId));
        Assert.Equal(store.AlertId, replay.AlertId);
        Assert.Equal(1, store.PublishCalls);
        Assert.Equal(store.AlertId, cache.Get(calculation.Id).PublishedAlertId);
    }

    [Fact]
    public async Task Failed_publication_remains_retryable()
    {
        var (service, cache, store) = Service();
        var calculation = cache.Create("held-out-01", Prediction(dangerous: true));
        store.FailNextPublish = true;

        await Assert.ThrowsAsync<HttpRequestException>(() => service.PublishAsync(calculation.Id, CancellationToken.None));
        var result = await service.PublishAsync(calculation.Id, CancellationToken.None);

        Assert.Equal(store.AlertId, result.AlertId);
        Assert.Equal(2, store.PublishCalls);
    }

    [Fact]
    public async Task Cleanup_commits_database_before_clearing_owned_cache()
    {
        var (service, cache, store) = Service();
        cache.Create("held-out-01", Prediction(dangerous: true));
        store.OnDelete = () => Assert.NotEmpty(cache.ActiveIds);

        await service.ClearAsync(CancellationToken.None);

        Assert.Equal(1, store.DeleteCalls);
        Assert.Empty(cache.ActiveIds);
    }

    private static (ModelDemoService Service, ModelDemoCalculationCache Cache, FakePublicationStore Store) Service(bool delayPublication = false)
    {
        var cache = new ModelDemoCalculationCache(
            new MemoryCache(new MemoryCacheOptions()),
            new FixedTimeProvider(new DateTimeOffset(2026, 9, 29, 9, 0, 0, TimeSpan.Zero)));
        var store = new FakePublicationStore { DelayPublication = delayPublication };
        var service = new ModelDemoService(Catalog(), new UnusedGateway(), cache, store);
        return (service, cache, store);
    }

    private static ModelDemoScenarioCatalog Catalog() => new(
        Path.Combine(AppContext.BaseDirectory, "Data", "model-demo-scenarios.json"));

    private static MlPrediction Prediction(bool dangerous) => new(
        "model-v1",
        new DateTimeOffset(2026, 9, 29, 9, 1, 0, TimeSpan.Zero),
        0.1,
        dangerous ? 0.8 : 0.2,
        dangerous ? 0.85 : 0.25,
        dangerous ? 0.9 : 0.3,
        new Dictionary<string, bool> { ["now"] = false, ["6h"] = dangerous, ["12h"] = dangerous, ["24h"] = dangerous },
        []);

    private sealed class FakePublicationStore : IModelDemoPublicationStore
    {
        public Guid AlertId { get; } = Guid.Parse("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
        public int PublishCalls { get; private set; }
        public int DeleteCalls { get; private set; }
        public bool FailNextPublish { get; set; }
        public bool DelayPublication { get; set; }
        public Action? OnDelete { get; set; }

        public async Task<Guid> PublishAsync(Guid calculationId, ModelDemoScenario scenario, MlPrediction prediction, CancellationToken cancellationToken)
        {
            PublishCalls++;
            if (DelayPublication) await Task.Delay(25, cancellationToken);
            if (FailNextPublish)
            {
                FailNextPublish = false;
                throw new HttpRequestException("database unavailable");
            }
            return AlertId;
        }

        public Task DeleteResultsAsync(CancellationToken cancellationToken)
        {
            DeleteCalls++;
            OnDelete?.Invoke();
            return Task.CompletedTask;
        }
    }

    private sealed class UnusedGateway : IMlGateway
    {
        public Task<object?> GetModelAsync(CancellationToken cancellationToken) => Task.FromResult<object?>(null);
        public Task<MlPrediction> PredictAsync(PredictRequest request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("not used");
    }

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }
}
