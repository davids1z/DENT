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

    public async Task<List<MlForensicResult>> RunForensicsBatchAsync(
        List<(byte[] Data, string FileName)> files, CancellationToken ct = default)
    {
        if (files.Count == 0) return [];
        if (files.Count == 1)
        {
            var single = await RunForensicsAsync(files[0].Data, files[0].FileName, ct);
            return [single];
        }

        try
        {
            using var content = new MultipartFormDataContent();
            for (int i = 0; i < files.Count; i++)
            {
                var byteContent = new ByteArrayContent(files[i].Data);
                byteContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                    GetContentType(files[i].FileName));
                content.Add(byteContent, "files", files[i].FileName);
            }

            var response = await _httpClient.PostAsync("/forensics/batch", content, ct);
            response.EnsureSuccessStatusCode();

            var results = await response.Content.ReadFromJsonAsync<List<MlForensicResult>>(SnakeCaseOptions, ct);
            return results ?? files.Select(_ => new MlForensicResult()).ToList();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Batch forensics failed, falling back to sequential");
            // Fallback: process sequentially
            var results = new List<MlForensicResult>();
            foreach (var (data, fileName) in files)
            {
                try { results.Add(await RunForensicsAsync(data, fileName, ct)); }
                catch { results.Add(new MlForensicResult()); }
            }
            return results;
        }
    }

    public async Task<MlBatchGroupResult> RunForensicsBatchGroupAsync(
        List<(byte[] Data, string FileName)> files, CancellationToken ct = default)
    {
        try
        {
            using var content = new MultipartFormDataContent();
            foreach (var (data, fileName) in files)
            {
                var byteContent = new ByteArrayContent(data);
                byteContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                    GetContentType(fileName));
                content.Add(byteContent, "files", fileName);
            }

            var response = await _httpClient.PostAsync("/forensics/batch-group", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlBatchGroupResult>(SnakeCaseOptions, ct);
            return result ?? new MlBatchGroupResult();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Batch-group endpoint failed, falling back to regular batch");
            // Fallback: run regular batch, no cross-image analysis
            var regularResults = await RunForensicsBatchAsync(files, ct);
            return new MlBatchGroupResult { PerFileReports = regularResults };
        }
    }

    public async Task<MlAnalysisResult> AnalyzeImageWithContextAsync(
        byte[] imageData, string fileName,
        MlForensicResult forensicContext,
        string? captureSource = null,
        CancellationToken ct = default)
    {
        try
        {
            // Serialize forensic context to JSON (snake_case for Python service)
            var forensicJson = JsonSerializer.Serialize(forensicContext, SnakeCaseOptions);

            using var content = new MultipartFormDataContent();
            using var byteContent = new ByteArrayContent(imageData);
            byteContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(
                GetContentType(fileName));
            content.Add(byteContent, "file", fileName);
            content.Add(new StringContent(forensicJson, Encoding.UTF8, "text/plain"), "forensic_context");
            if (!string.IsNullOrEmpty(captureSource))
                content.Add(new StringContent(captureSource), "capture_source");

            var response = await _httpClient.PostAsync("/analyze-with-context", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlAnalysisResult>(SnakeCaseOptions, ct);
            return result ?? new MlAnalysisResult { Success = false, ErrorMessage = "Empty response from ML service" };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Context-aware analysis failed for {FileName}, falling back to standard analysis", fileName);
            // Fallback to standard analysis without context
            using var stream = new MemoryStream(imageData);
            return await AnalyzeImageAsync(stream, fileName, ct);
        }
    }

    public async Task<MlAgentDecision?> RunAgentEvaluationAsync(MlAgentEvaluateRequest request, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(request, SnakeCaseOptions);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/agent/evaluate", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlAgentDecision>(SnakeCaseOptions, ct);
            return result;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Agent evaluation failed, will fall back to rule engine");
            return null;
        }
    }

    public async Task<MlTimestampResult> ObtainTimestampAsync(string evidenceHash, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(new { evidence_hash = evidenceHash });
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/evidence/timestamp", content, ct);
            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<MlTimestampResult>(SnakeCaseOptions, ct);
            return result ?? new MlTimestampResult { Success = false, Error = "Empty response" };
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to obtain RFC 3161 timestamp");
            return new MlTimestampResult { Success = false, Error = ex.Message };
        }
    }

    public async Task<byte[]?> GenerateReportAsync(object payload, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(payload, SnakeCaseOptions);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/evidence/report", content, ct);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadAsByteArrayAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to generate evidence report");
            return null;
        }
    }

    public async Task<byte[]?> GenerateCertificateAsync(object payload, CancellationToken ct = default)
    {
        try
        {
            var json = JsonSerializer.Serialize(payload, SnakeCaseOptions);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var response = await _httpClient.PostAsync("/evidence/certificate", content, ct);
            response.EnsureSuccessStatusCode();

            return await response.Content.ReadAsByteArrayAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to generate evidence certificate");
            return null;
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
            ".pdf" => "application/pdf",
            _ => "application/octet-stream"
        };
    }
}
