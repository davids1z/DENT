using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Domain.Enums;

namespace DENT.API.Services;

public class BackgroundAnalysisService : BackgroundService
{
    private readonly IAnalysisQueue _queue;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<BackgroundAnalysisService> _logger;

    /// <summary>
    /// Number of concurrent inspection processing loops.
    /// Each loop dequeues from the shared Channel independently,
    /// allowing N inspections to be analyzed simultaneously.
    /// </summary>
    private const int MaxConcurrency = 3;

    public BackgroundAnalysisService(
        IAnalysisQueue queue,
        IServiceScopeFactory scopeFactory,
        ILogger<BackgroundAnalysisService> logger)
    {
        _queue = queue;
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "Background analysis service started with {Concurrency} concurrent workers",
            MaxConcurrency);

        // Spawn N independent processing loops, each dequeuing from the same Channel.
        // Channel<T> is thread-safe, so multiple readers work correctly.
        var workers = Enumerable.Range(0, MaxConcurrency)
            .Select(i => ProcessLoop(i, stoppingToken))
            .ToArray();

        await Task.WhenAll(workers);

        _logger.LogInformation("Background analysis service stopped");
    }

    private async Task ProcessLoop(int workerId, CancellationToken stoppingToken)
    {
        _logger.LogInformation("Analysis worker {WorkerId} started", workerId);

        while (!stoppingToken.IsCancellationRequested)
        {
            Guid? inspectionId = null;
            try
            {
                var data = await _queue.DequeueAsync(stoppingToken);
                inspectionId = data.InspectionId;

                _logger.LogInformation(
                    "Worker {WorkerId}: starting analysis for inspection {Id} (queue: {QueueCount} pending, {ActiveUsers} users)",
                    workerId, inspectionId, _queue.Count, _queue.ActiveUserCount);

                using var scope = _scopeFactory.CreateScope();
                var orchestrator = scope.ServiceProvider
                    .GetRequiredService<IForensicOrchestrationService>();
                await orchestrator.RunAnalysisAsync(data, stoppingToken);

                _logger.LogInformation(
                    "Worker {WorkerId}: completed analysis for inspection {Id}",
                    workerId, inspectionId);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex,
                    "Worker {WorkerId}: analysis failed for inspection {Id}",
                    workerId, inspectionId);

                if (inspectionId.HasValue)
                    await MarkInspectionFailed(inspectionId.Value, ex.Message);
            }
        }

        _logger.LogInformation("Analysis worker {WorkerId} stopped", workerId);
    }

    private async Task MarkInspectionFailed(Guid inspectionId, string error)
    {
        try
        {
            using var scope = _scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<IDentDbContext>();
            var inspection = await db.Inspections.FindAsync(inspectionId);
            if (inspection != null)
            {
                inspection.Status = InspectionStatus.Failed;
                inspection.ErrorMessage = error;
                await db.SaveChangesAsync(CancellationToken.None);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to mark inspection {Id} as failed", inspectionId);
        }
    }
}
