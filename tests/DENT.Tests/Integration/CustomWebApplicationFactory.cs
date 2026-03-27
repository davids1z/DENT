using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Infrastructure.Data;
using DENT.Infrastructure.Services;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Options;

namespace DENT.Tests.Integration;

public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    private readonly string _dbName = "TestDb_" + Guid.NewGuid().ToString("N");

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Development");

        builder.ConfigureServices(services =>
        {
            // Remove ALL EF Core + infrastructure descriptors
            var toRemove = services.Where(d =>
                d.ServiceType == typeof(DbContextOptions<DentDbContext>) ||
                d.ServiceType == typeof(DbContextOptions) ||
                d.ServiceType.FullName?.Contains("EntityFrameworkCore") == true ||
                d.ServiceType.FullName?.Contains("Npgsql") == true ||
                d.ServiceType == typeof(Amazon.S3.IAmazonS3) ||
                d.ServiceType == typeof(IStorageService) ||
                d.ServiceType == typeof(IMlAnalysisService) ||
                d.ServiceType == typeof(IDentDbContext) ||
                d.ServiceType == typeof(DentDbContext) ||
                d.ImplementationType == typeof(StorageService) ||
                d.ImplementationType == typeof(MlAnalysisService) ||
                d.ImplementationType == typeof(DentDbContext)
            ).ToList();
            foreach (var d in toRemove) services.Remove(d);

            // Unique DB per factory instance (shared within a test class via IClassFixture)
            var dbName = _dbName;
            services.AddDbContext<DentDbContext>(options =>
                options.UseInMemoryDatabase(dbName));
            services.AddScoped<IDentDbContext>(sp => sp.GetRequiredService<DentDbContext>());

            // Stubs
            services.AddScoped<IStorageService>(_ => new StubStorageService());
            services.AddScoped<IMlAnalysisService>(_ => new StubMlAnalysisService());
        });
    }
}

public class StubStorageService : IStorageService
{
    public Task<string> UploadAsync(Stream stream, string fileName, string contentType, CancellationToken ct = default)
        => Task.FromResult($"inspections/test/{Guid.NewGuid()}{Path.GetExtension(fileName)}");

    public string GetPublicUrl(string key) => $"https://test-storage/{key}";

    public Task DeleteAsync(string key, CancellationToken ct = default) => Task.CompletedTask;
}

public class StubMlAnalysisService : IMlAnalysisService
{
    public Task<MlAnalysisResult> AnalyzeImageAsync(Stream imageStream, string fileName, CancellationToken ct = default)
        => Task.FromResult(new MlAnalysisResult { Success = true });

    public Task<MlAnalysisResult> AnalyzeMultipleImagesAsync(
        List<MlImageInput> images, string? vehicleMake, string? vehicleModel, int? vehicleYear, int? mileage, CancellationToken ct = default)
        => Task.FromResult(new MlAnalysisResult { Success = true });

    public Task<MlForensicResult> RunForensicsAsync(byte[] fileBytes, string fileName, CancellationToken ct = default)
        => Task.FromResult(new MlForensicResult
        {
            OverallRiskScore = 0.05,
            OverallRiskScore100 = 5,
            OverallRiskLevel = "Low",
            Modules = [],
            TotalProcessingTimeMs = 100,
        });

    public Task<MlAnalysisResult> AnalyzeImageWithContextAsync(
        byte[] imageData, string fileName, MlForensicResult forensicContext, string? captureSource = null, CancellationToken ct = default)
        => Task.FromResult(new MlAnalysisResult { Success = true });

    public Task<MlAgentDecision?> RunAgentEvaluationAsync(MlAgentEvaluateRequest request, CancellationToken ct = default)
        => Task.FromResult<MlAgentDecision?>(null);

    public Task<MlTimestampResult> ObtainTimestampAsync(string evidenceHash, CancellationToken ct = default)
        => Task.FromResult(new MlTimestampResult { Success = true, TimestampToken = "test-token", TimestampedAt = DateTime.UtcNow.ToString("o"), TsaUrl = "https://test-tsa" });

    public Task<byte[]?> GenerateReportAsync(object payload, CancellationToken ct = default)
        => Task.FromResult<byte[]?>(new byte[] { 0x25, 0x50, 0x44, 0x46 });

    public Task<byte[]?> GenerateCertificateAsync(object payload, CancellationToken ct = default)
        => Task.FromResult<byte[]?>(System.Text.Encoding.UTF8.GetBytes("<xml/>"));
}
