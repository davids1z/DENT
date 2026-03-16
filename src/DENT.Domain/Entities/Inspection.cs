using DENT.Domain.Enums;

namespace DENT.Domain.Entities;

public class Inspection
{
    public Guid Id { get; set; }
    public string ImageUrl { get; set; } = string.Empty;
    public string OriginalFileName { get; set; } = string.Empty;
    public string? ThumbnailUrl { get; set; }
    public InspectionStatus Status { get; set; } = InspectionStatus.Pending;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? CompletedAt { get; set; }

    // User-provided vehicle context (before upload)
    public string? UserProvidedMake { get; set; }
    public string? UserProvidedModel { get; set; }
    public int? UserProvidedYear { get; set; }
    public int? Mileage { get; set; }

    // Capture metadata (Phase 6)
    public double? CaptureLatitude { get; set; }
    public double? CaptureLongitude { get; set; }
    public double? CaptureGpsAccuracy { get; set; }
    public string? CaptureDeviceInfo { get; set; }
    public string? CaptureSource { get; set; }

    // Vehicle info (detected by AI)
    public string? VehicleMake { get; set; }
    public string? VehicleModel { get; set; }
    public int? VehicleYear { get; set; }
    public string? VehicleColor { get; set; }

    // Overall assessment
    public string? Summary { get; set; }
    public decimal? TotalEstimatedCostMin { get; set; }
    public decimal? TotalEstimatedCostMax { get; set; }
    public string Currency { get; set; } = "EUR";
    public bool? IsDriveable { get; set; }
    public string? UrgencyLevel { get; set; }
    public string? StructuralIntegrity { get; set; }
    public string? ErrorMessage { get; set; }

    // Structured cost totals
    public decimal? LaborTotal { get; set; }
    public decimal? PartsTotal { get; set; }
    public decimal? MaterialsTotal { get; set; }
    public decimal? GrossTotal { get; set; }

    // Decision engine
    public string? DecisionOutcome { get; set; } // AutoApprove, HumanReview, Escalate
    public string? DecisionReason { get; set; }
    public string? DecisionTraceJson { get; set; } // JSON array of rule evaluations

    // Fraud detection
    public double? FraudRiskScore { get; set; }
    public string? FraudRiskLevel { get; set; }

    // Navigation
    public List<DamageDetection> Damages { get; set; } = [];
    public List<InspectionImage> AdditionalImages { get; set; } = [];
    public List<DecisionOverride> DecisionOverrides { get; set; } = [];
    public ForensicResult? ForensicResult { get; set; }
}
