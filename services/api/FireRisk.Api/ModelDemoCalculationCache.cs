using System.Collections.Concurrent;
using Microsoft.Extensions.Caching.Memory;

namespace FireRisk.Api;

public sealed record DemoCalculation(
    Guid Id,
    string ScenarioId,
    MlPrediction Prediction,
    DateTimeOffset ExpiresAt,
    Guid? PublishedAlertId = null);

public sealed class ModelDemoCalculationCache(IMemoryCache cache, TimeProvider clock)
{
    private static readonly TimeSpan Lifetime = TimeSpan.FromMinutes(30);
    private readonly ConcurrentDictionary<Guid, byte> ownedKeys = new();

    public IReadOnlyCollection<Guid> ActiveIds => ownedKeys.Keys.ToArray();

    public DemoCalculation Create(string scenarioId, MlPrediction prediction)
    {
        var calculation = new DemoCalculation(Guid.NewGuid(), scenarioId, prediction, clock.GetUtcNow() + Lifetime);
        cache.Set(calculation.Id, calculation, Lifetime);
        ownedKeys[calculation.Id] = 0;
        return calculation;
    }

    public DemoCalculation Get(Guid id)
    {
        if (!cache.TryGetValue<DemoCalculation>(id, out var calculation) || calculation is null || calculation.ExpiresAt <= clock.GetUtcNow())
        {
            Remove(id);
            throw new KeyNotFoundException("calculation not found or expired");
        }
        return calculation;
    }

    public DemoCalculation MarkPublished(Guid id, Guid alertId)
    {
        var current = Get(id);
        var updated = current with { PublishedAlertId = alertId };
        cache.Set(id, updated, current.ExpiresAt - clock.GetUtcNow());
        return updated;
    }

    public void Clear()
    {
        foreach (var id in ownedKeys.Keys) Remove(id);
    }

    private void Remove(Guid id)
    {
        cache.Remove(id);
        ownedKeys.TryRemove(id, out _);
    }
}
