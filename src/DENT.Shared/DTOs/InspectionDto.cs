namespace DENT.Shared.DTOs;

public record InspectionDto
{
    public Guid Id { get; init; }
    public string ImageUrl { get; init; } = string.Empty;
    public string OriginalFileName { get; init; } = string.Empty;
    public string? ThumbnailUrl { get; init; }
    public string Status { get; init; } = string.Empty;
    public DateTime CreatedAt { get; init; }
    public DateTime? CompletedAt { get; init; }

    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public string? VehicleColor { get; init; }

    public string? Summary { get; init; }
    public decimal? TotalEstimatedCostMin { get; init; }
    public decimal? TotalEstimatedCostMax { get; init; }
    public string Currency { get; init; } = "EUR";
    public bool? IsDriveable { get; init; }
    public string? UrgencyLevel { get; init; }
    public string? ErrorMessage { get; init; }

    public List<DamageDetectionDto> Damages { get; init; } = [];
}

public record DamageDetectionDto
{
    public Guid Id { get; init; }
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

public record DashboardStatsDto
{
    public int TotalInspections { get; init; }
    public int CompletedInspections { get; init; }
    public int PendingInspections { get; init; }
    public decimal AverageCostMin { get; init; }
    public decimal AverageCostMax { get; init; }
    public Dictionary<string, int> DamageTypeDistribution { get; init; } = [];
    public Dictionary<string, int> SeverityDistribution { get; init; } = [];
    public Dictionary<string, int> CarPartDistribution { get; init; } = [];
    public List<InspectionDto> RecentInspections { get; init; } = [];
}