namespace DENT.Domain.Entities;

public class ForensicResult
{
    public Guid Id { get; set; }
    public Guid InspectionId { get; set; }

    public double OverallRiskScore { get; set; }
    public int OverallRiskScore100 { get; set; }
    public string OverallRiskLevel { get; set; } = "Low";

    // Per-module results stored as JSON array
    public string ModuleResultsJson { get; set; } = "[]";

    // Visual artifact URLs (stored in MinIO)
    public string? ElaHeatmapUrl { get; set; }
    public string? FftSpectrumUrl { get; set; }
    public string? SpectralHeatmapUrl { get; set; }

    // Source generator attribution
    public string? PredictedSource { get; set; }
    public int SourceConfidence { get; set; }

    // C2PA provenance
    public string? C2paStatus { get; set; }
    public string? C2paIssuer { get; set; }

    public int TotalProcessingTimeMs { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public Inspection Inspection { get; set; } = null!;
}
