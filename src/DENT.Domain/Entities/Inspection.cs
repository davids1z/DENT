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
    public string? ErrorMessage { get; set; }

    // Navigation
    public List<DamageDetection> Damages { get; set; } = [];
}
