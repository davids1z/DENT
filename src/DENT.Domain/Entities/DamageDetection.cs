using DENT.Domain.Enums;

namespace DENT.Domain.Entities;

public class DamageDetection
{
    public Guid Id { get; set; }
    public Guid InspectionId { get; set; }

    public DamageType DamageType { get; set; }
    public CarPart CarPart { get; set; }
    public DamageSeverity Severity { get; set; }

    public string Description { get; set; } = string.Empty;
    public double Confidence { get; set; }

    // Repair info
    public string? RepairMethod { get; set; }
    public decimal? EstimatedCostMin { get; set; }
    public decimal? EstimatedCostMax { get; set; }
    public double? LaborHours { get; set; }
    public string? PartsNeeded { get; set; }

    // Navigation
    public Inspection Inspection { get; set; } = null!;
}
