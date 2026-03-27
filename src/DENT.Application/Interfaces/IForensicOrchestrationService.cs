using DENT.Application.Models;

namespace DENT.Application.Interfaces;

public interface IForensicOrchestrationService
{
    Task RunAnalysisAsync(BackgroundAnalysisData data, CancellationToken ct);
}
