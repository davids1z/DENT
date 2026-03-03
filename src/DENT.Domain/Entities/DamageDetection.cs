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

    // Forensic fields
    public string? BoundingBox { get; set; } // JSON: {"x":0.3,"y":0.4,"w":0.15,"h":0.1}
    public string? DamageCause { get; set; }
    public string? SafetyRating { get; set; } // Safe, Warning, Critical
    public string? MaterialType { get; set; }
    public string? RepairOperations { get; set; }
    public string? RepairCategory { get; set; } // Replace, Repair, Polish

    // Structured repair line items (JSON array)
    public string? RepairLineItemsJson { get; set; }

    // Navigation
    public Inspection Inspection { get; set; } = null!;
}
