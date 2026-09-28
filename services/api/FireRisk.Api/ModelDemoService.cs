namespace FireRisk.Api;

public sealed class ModelDemoService(
    ModelDemoScenarioCatalog catalog,
    IMlGateway ml,
    ModelDemoCalculationCache cache)
{
    public IReadOnlyList<ModelDemoScenarioSummary> List() => catalog.List();

    public async Task<ModelDemoPredictionResponse> PredictAsync(string scenarioId, CancellationToken cancellationToken)
    {
        var scenario = catalog.Get(scenarioId);
        var request = new PredictRequest(scenario.Features.ToDictionary(pair => pair.Key, pair => pair.Value), 5);
        var prediction = await ml.PredictAsync(request, cancellationToken);
        var calculation = cache.Create(scenario.Id, prediction);
        return new ModelDemoPredictionResponse(calculation.Id, scenario.ToSummary(), prediction);
    }
}
