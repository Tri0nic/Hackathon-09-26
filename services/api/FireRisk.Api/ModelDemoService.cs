namespace FireRisk.Api;

using System.Collections.Concurrent;

public sealed class ModelDemoService(
    ModelDemoScenarioCatalog catalog,
    IMlGateway ml,
    ModelDemoCalculationCache cache,
    IModelDemoPublicationStore publicationStore)
{
    private readonly ConcurrentDictionary<Guid, SemaphoreSlim> publicationLocks = new();

    public IReadOnlyList<ModelDemoScenarioSummary> List() => catalog.List();

    public async Task<ModelDemoPredictionResponse> PredictAsync(string scenarioId, CancellationToken cancellationToken)
    {
        var scenario = catalog.Get(scenarioId);
        var request = new PredictRequest(scenario.Features.ToDictionary(pair => pair.Key, pair => pair.Value), 5);
        var prediction = await ml.PredictAsync(request, cancellationToken);
        var calculation = cache.Create(scenario.Id, prediction);
        return new ModelDemoPredictionResponse(calculation.Id, scenario.ToSummary(), prediction);
    }

    public async Task<ModelDemoPublicationResponse> PublishAsync(Guid calculationId, CancellationToken cancellationToken)
    {
        var gate = publicationLocks.GetOrAdd(calculationId, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken);
        try
        {
            var calculation = cache.Get(calculationId);
            if (calculation.PublishedAlertId is Guid existingId)
                return new ModelDemoPublicationResponse(existingId);
            if (!calculation.Prediction.Decisions.Values.Any(value => value))
                throw new InvalidOperationException("prediction threshold was not exceeded");
            var scenario = catalog.Get(calculation.ScenarioId);
            var alertId = await publicationStore.PublishAsync(calculationId, scenario, calculation.Prediction, cancellationToken);
            cache.MarkPublished(calculationId, alertId);
            return new ModelDemoPublicationResponse(alertId);
        }
        finally
        {
            gate.Release();
        }
    }

    public async Task ClearAsync(CancellationToken cancellationToken)
    {
        await publicationStore.DeleteResultsAsync(cancellationToken);
        cache.Clear();
        foreach (var pair in publicationLocks)
            if (publicationLocks.TryRemove(pair.Key, out var gate)) gate.Dispose();
    }
}
