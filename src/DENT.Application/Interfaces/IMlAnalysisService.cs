using DENT.Domain.Entities;

namespace DENT.Application.Interfaces;

public interface IMlAnalysisService
{
    Task<MlAnalysisResult> AnalyzeImageAsync(Stream imageStream, string fileName, CancellationToken ct = default);
}

public record MlAnalysisResult
{
    public bool Success { get; init; }
    public string? ErrorMessage { get; init; }
    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public string? VehicleColor { get; init; }
    public string? Summary { get; init; }
    public decimal? TotalEstimatedCostMin { get; init; }
    public decimal? TotalEstimatedCostMax { get; init; }
    public bool? IsDriveable { get; init; }
    public string? UrgencyLevel { get; init; }
    public List<MlDamageResult> Damages { get; init; } = [];
}

public record MlDamageResult
{
    public string DamageType { get; init; } = string.Empty;
    public string CarPart { get; init; } = string.Empty;
    public string Severity { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public double Confidence { get; init; }
    public string? RepairMethod { get; init; }
    public decimal? EstimatedCostMin { get; init; }
    public decimal? EstimatedCostMax { get; init; }
    public double? LaborHours { get; init; }
    public string? PartsNeeded { get; init; }
}
