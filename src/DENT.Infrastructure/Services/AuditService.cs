using System.Threading.Channels;
using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using DENT.Infrastructure.Data;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace DENT.Infrastructure.Services;

public class AuditService : IAuditService
{
    private readonly Channel<AuditEventData> _channel;

    public AuditService(Channel<AuditEventData> channel)
    {
        _channel = channel;
    }

    public void Track(AuditEventData data)
    {
        _channel.Writer.TryWrite(data);
    }
}

/// <summary>
/// Reads from the audit channel and batch-inserts events into PostgreSQL
/// every 2 seconds or when 100 events accumulate.
/// </summary>
public class AuditFlushService : BackgroundService
{
    private readonly Channel<AuditEventData> _channel;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ILogger<AuditFlushService> _logger;

    private const int BatchSize = 100;
    private static readonly TimeSpan FlushInterval = TimeSpan.FromSeconds(2);

    public AuditFlushService(
        Channel<AuditEventData> channel,
        IServiceScopeFactory scopeFactory,
        ILogger<AuditFlushService> logger)
    {
        _channel = channel;
        _scopeFactory = scopeFactory;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Audit flush service started");
        var buffer = new List<AuditEvent>(BatchSize);

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
                cts.CancelAfter(FlushInterval);

                try
                {
                    while (buffer.Count < BatchSize)
                    {
                        var data = await _channel.Reader.ReadAsync(cts.Token);
                        buffer.Add(MapToEntity(data));
                    }
                }
                catch (OperationCanceledException) when (!stoppingToken.IsCancellationRequested)
                {
                    // Flush interval elapsed — flush whatever we have
                }

                if (buffer.Count > 0)
                {
                    await FlushBatch(buffer, stoppingToken);
                    buffer.Clear();
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                if (buffer.Count > 0)
                    await FlushBatch(buffer, CancellationToken.None);
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Audit flush error, dropping {Count} events", buffer.Count);
                buffer.Clear();
            }
        }

        _logger.LogInformation("Audit flush service stopped");
    }

    private async Task FlushBatch(List<AuditEvent> batch, CancellationToken ct)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<DentDbContext>();
        db.AuditEvents.AddRange(batch);
        await db.SaveChangesAsync(ct);
        _logger.LogDebug("Flushed {Count} audit events", batch.Count);
    }

    private static AuditEvent MapToEntity(AuditEventData d) => new()
    {
        Timestamp = DateTime.UtcNow,
        EventType = d.EventType,
        Category = d.Category,
        Method = d.Method,
        Path = d.Path,
        StatusCode = d.StatusCode,
        DurationMs = d.DurationMs,
        UserId = d.UserId,
        SessionId = d.SessionId,
        IpAddress = d.IpAddress,
        UserAgent = d.UserAgent?.Length > 500 ? d.UserAgent[..500] : d.UserAgent,
        MetadataJson = d.MetadataJson,
        ResourceId = d.ResourceId,
        ResourceType = d.ResourceType,
    };
}
