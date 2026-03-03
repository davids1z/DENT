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

    // User-provided vehicle context
    public string? UserProvidedMake { get; init; }
    public string? UserProvidedModel { get; init; }
    public int? UserProvidedYear { get; init; }
    public int? Mileage { get; init; }

    // AI-detected vehicle info
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
    public string? StructuralIntegrity { get; init; }
    public string? ErrorMessage { get; init; }

    // Structured totals
    public decimal? LaborTotal { get; init; }
    public decimal? PartsTotal { get; init; }
    public decimal? MaterialsTotal { get; init; }
    public decimal? GrossTotal { get; init; }

    // Decision engine
    public string? DecisionOutcome { get; init; }
    public string? DecisionReason { get; init; }
    public List<DecisionTraceEntryDto> DecisionTraces { get; init; } = [];
    public List<DecisionOverrideDto> DecisionOverrides { get; init; } = [];

    // Multi-image
    public List<InspectionImageDto> AdditionalImages { get; init; } = [];

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
    public string? BoundingBox { get; init; }
    public string? DamageCause { get; init; }
    public string? SafetyRating { get; init; }
    public string? MaterialType { get; init; }
    public string? RepairOperations { get; init; }
    public string? RepairCategory { get; init; }
    public List<RepairLineItemDto> RepairLineItems { get; init; } = [];
}

public record RepairLineItemDto
{
    public int LineNumber { get; init; }
    public string PartName { get; init; } = string.Empty;
    public string Operation { get; init; } = string.Empty;
    public string LaborType { get; init; } = string.Empty;
    public double LaborHours { get; init; }
    public string PartType { get; init; } = "Existing";
    public int Quantity { get; init; } = 1;
    public decimal? UnitCost { get; init; }
    public decimal? TotalCost { get; init; }
}

public record InspectionImageDto
{
    public Guid Id { get; init; }
    public string ImageUrl { get; init; } = string.Empty;
    public string OriginalFileName { get; init; } = string.Empty;
    public int SortOrder { get; init; }
}

public record DecisionTraceEntryDto
{
    public string RuleName { get; init; } = string.Empty;
    public string RuleDescription { get; init; } = string.Empty;
    public bool Triggered { get; init; }
    public string? ThresholdValue { get; init; }
    public string? ActualValue { get; init; }
    public int EvaluationOrder { get; init; }
}

public record DecisionOverrideDto
{
    public string OriginalOutcome { get; init; } = string.Empty;
    public string NewOutcome { get; init; } = string.Empty;
    public string Reason { get; init; } = string.Empty;
    public string OperatorName { get; init; } = string.Empty;
    public DateTime CreatedAt { get; init; }
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
    public Dictionary<string, int> DecisionOutcomeDistribution { get; init; } = [];
    public List<InspectionDto> RecentInspections { get; init; } = [];
}
