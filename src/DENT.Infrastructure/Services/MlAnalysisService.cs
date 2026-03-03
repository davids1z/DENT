using System.Net.Http.Json;
using DENT.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace DENT.Infrastructure.Services;

public class MlAnalysisService : IMlAnalysisService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<MlAnalysisService> _logger;

    public MlAnalysisService(HttpClient httpClient, IConfiguration config, ILogger<MlAnalysisService> logger)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = new Uri(config["MlService:BaseUrl"] ?? "http://ml-service:8000");
        _httpClient.Timeout = TimeSpan.FromMinutes(2);
        _logger = logger;
    }

    public async Task<MlAnalysisResult> AnalyzeImageAsync(Stream imageStream, string fileName, CancellationToken ct = default)
    {
        try
        {
            using var content = new MultipartFormDataContent();
            using var streamContent = new StreamContent(imageStream);
            streamContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                GetContentType(fileName));
            content.Add(streamContent, "file", fileName);

            var response = await _httpClient.PostAsync("/analyze", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlAnalysisResult>(ct);
            return result ?? new MlAnalysisResult { Success = false, ErrorMessage = "Empty response from ML service" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error calling ML service for {FileName}", fileName);
            return new MlAnalysisResult { Success = false, ErrorMessage = ex.Message };
        }
    }

    private static string GetContentType(string fileName)
    {
        var ext = Path.GetExtension(fileName).ToLowerInvariant();
        return ext switch
        {
            ".jpg" or ".jpeg" => "image/jpeg",
            ".png" => "image/png",
            ".webp" => "image/webp",
            ".heic" => "image/heic",
            _ => "application/octet-stream"
        };
    }
}
