using DENT.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace DENT.API.Services;

public class AuditRetentionService : BackgroundService
{
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<AuditRetentionService> _logger;
    private readonly int _retentionDays;

    public AuditRetentionService(
        IServiceScopeFactory scopeFactory,
        IConfiguration config,
        ILogger<AuditRetentionService> logger)
    {
        _scopeFactory = scopeFactory;
        _logger = logger;
        _retentionDays = int.TryParse(config["Audit:RetentionDays"], out var d) ? d : 90;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Wait 1 hour after startup before first cleanup
        await Task.Delay(TimeSpan.FromHours(1), stoppingToken);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var cutoff = DateTime.UtcNow.AddDays(-_retentionDays);
                using var scope = _scopeFactory.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<DentDbContext>();

                var deleted = await db.Database.ExecuteSqlRawAsync(
                    "DELETE FROM \"AuditEvents\" WHERE \"Timestamp\" < {0}", cutoff);

                if (deleted > 0)
                    _logger.LogInformation("Audit retention: deleted {Count} events older than {Days} days", deleted, _retentionDays);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Audit retention cleanup failed");
            }

            await Task.Delay(TimeSpan.FromHours(24), stoppingToken);
        }
    }
}
