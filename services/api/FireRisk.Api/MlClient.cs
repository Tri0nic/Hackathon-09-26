using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;

namespace FireRisk.Api;

public interface IMlGateway
{
    Task<MlPrediction> PredictAsync(PredictRequest request, CancellationToken cancellationToken);
    Task<object?> GetModelAsync(CancellationToken cancellationToken);
}

public sealed class MlClient(HttpClient httpClient) : IMlGateway
{
    public async Task<MlPrediction> PredictAsync(PredictRequest request, CancellationToken cancellationToken)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(request, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        using var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        using var response = await httpClient.PostAsync("/ml/predict", content, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<MlPrediction>(cancellationToken)
            ?? throw new InvalidOperationException("ML returned an empty response");
    }

    public async Task<object?> GetModelAsync(CancellationToken cancellationToken)
    {
        using var response = await httpClient.GetAsync("/ml/models/current", cancellationToken);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<object>(cancellationToken);
    }
}
