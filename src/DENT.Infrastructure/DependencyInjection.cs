using Amazon.S3;
using DENT.Application.Interfaces;
using DENT.Infrastructure.Data;
using DENT.Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace DENT.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        // Database
        services.AddDbContext<DentDbContext>(options =>
            options.UseNpgsql(configuration.GetConnectionString("DefaultConnection")));
        services.AddScoped<IDentDbContext>(sp => sp.GetRequiredService<DentDbContext>());

        // S3/MinIO Storage
        services.AddSingleton<IAmazonS3>(_ =>
        {
            var config = new AmazonS3Config
            {
                ServiceURL = configuration["Storage:ServiceUrl"] ?? "http://minio:9000",
                ForcePathStyle = true
            };
            return new AmazonS3Client(
                configuration["Storage:AccessKey"] ?? "minioadmin",
                configuration["Storage:SecretKey"] ?? "minioadmin",
                config);
        });

        services.AddScoped<IStorageService, StorageService>();
        services.AddScoped<IAuthService, AuthService>();

        // ML Service HTTP Client
        services.AddHttpClient<IMlAnalysisService, MlAnalysisService>();

        return services;
    }
}
