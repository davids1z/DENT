using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using DENT.Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace DENT.Infrastructure.Services;

public class MlAnalysisService : IMlAnalysisService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<MlAnalysisService> _logger;

    private static readonly JsonSerializerOptions SnakeCaseOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true
    };

    public MlAnalysisService(HttpClient httpClient, IConfiguration config, ILogger<MlAnalysisService> logger)
    {
        _httpClient = httpClient;
        _httpClient.BaseAddress = new Uri(config["MlService:BaseUrl"] ?? "http://ml-service:8000");
        _httpClient.Timeout = TimeSpan.FromMinutes(5);
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

            var result = await response.Content.ReadFromJsonAsync<MlAnalysisResult>(SnakeCaseOptions, ct);
            return result ?? new MlAnalysisResult { Success = false, ErrorMessage = "Empty response from ML service" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error calling ML service for {FileName}", fileName);
            return new MlAnalysisResult { Success = false, ErrorMessage = ex.Message };
        }
    }

    public async Task<MlAnalysisResult> AnalyzeMultipleImagesAsync(
        List<MlImageInput> images,
        string? vehicleMake, string? vehicleModel, int? vehicleYear, int? mileage,
        CancellationToken ct = default)
    {
        try
        {
            var requestBody = new
            {
                images = images.Select(img => new
                {
                    data = Convert.ToBase64String(img.Data),
                    media_type = GetContentType(img.FileName),
                    filename = img.FileName,
                }).ToArray(),
                vehicle_make = vehicleMake,
                vehicle_model = vehicleModel,
                vehicle_year = vehicleYear,
                mileage = mileage,
            };

            var json = JsonSerializer.Serialize(requestBody);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/analyze-multi", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlAnalysisResult>(SnakeCaseOptions, ct);
            return result ?? new MlAnalysisResult { Success = false, ErrorMessage = "Empty response from ML service" };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error calling ML multi-image service");
            return new MlAnalysisResult { Success = false, ErrorMessage = ex.Message };
        }
    }

    public async Task<MlForensicResult> RunForensicsAsync(byte[] fileBytes, string fileName, CancellationToken ct = default)
    {
        try
        {
            using var content = new MultipartFormDataContent();
            using var byteContent = new ByteArrayContent(fileBytes);
            byteContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                GetContentType(fileName));
            content.Add(byteContent, "file", fileName);

            var response = await _httpClient.PostAsync("/forensics", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlForensicResult>(SnakeCaseOptions, ct);
            return result ?? new MlForensicResult();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error calling forensics service for {FileName}", fileName);
            throw;
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
