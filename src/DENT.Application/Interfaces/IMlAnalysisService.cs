namespace DENT.Application.Interfaces;

public interface IMlAnalysisService
{
    Task<MlAnalysisResult> AnalyzeImageAsync(Stream imageStream, string fileName, CancellationToken ct = default);

    Task<MlAnalysisResult> AnalyzeMultipleImagesAsync(
        List<MlImageInput> images,
        string? vehicleMake, string? vehicleModel, int? vehicleYear, int? mileage,
        CancellationToken ct = default);

    Task<MlForensicResult> RunForensicsAsync(byte[] fileBytes, string fileName, CancellationToken ct = default);

    /// <summary>
    /// Context-aware analysis: sends the image together with forensic module results
    /// so Gemini synthesizes and explains forensic evidence rather than independently detecting.
    /// </summary>
    Task<MlAnalysisResult> AnalyzeImageWithContextAsync(
        byte[] imageData, string fileName,
        MlForensicResult forensicContext,
        string? captureSource = null,
        CancellationToken ct = default);

    Task<MlAgentDecision?> RunAgentEvaluationAsync(MlAgentEvaluateRequest request, CancellationToken ct = default);

    // Evidence (Phase 8)
    Task<MlTimestampResult> ObtainTimestampAsync(string evidenceHash, CancellationToken ct = default);
    Task<byte[]?> GenerateReportAsync(object payload, CancellationToken ct = default);
    Task<byte[]?> GenerateCertificateAsync(object payload, CancellationToken ct = default);
}

public record MlImageInput
{
    public required byte[] Data { get; init; }
    public required string FileName { get; init; }
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
    public string? StructuralIntegrity { get; init; }
    public List<MlDamageResult> Damages { get; init; } = [];
    // Structured totals
    public decimal? LaborTotal { get; init; }
    public decimal? PartsTotal { get; init; }
    public decimal? MaterialsTotal { get; init; }
    public decimal? GrossTotal { get; init; }
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
    public MlBoundingBox? BoundingBox { get; init; }
    public string? DamageCause { get; init; }
    public string? SafetyRating { get; init; }
    public string? MaterialType { get; init; }
    public string? RepairOperations { get; init; }
    public string? RepairCategory { get; init; }
    public List<MlRepairLineItem> RepairLineItems { get; init; } = [];
}

public record MlBoundingBox
{
    public double X { get; init; }
    public double Y { get; init; }
    public double W { get; init; }
    public double H { get; init; }
    public int ImageIndex { get; init; }
}

public record MlRepairLineItem
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

// Forensic analysis results
public record MlForensicResult
{
    public double OverallRiskScore { get; init; }
    public int OverallRiskScore100 { get; init; }
    public string OverallRiskLevel { get; init; } = "Low";
    public List<MlForensicModule> Modules { get; init; } = [];
    public string? ElaHeatmapB64 { get; init; }
    public string? FftSpectrumB64 { get; init; }
    public string? SpectralHeatmapB64 { get; init; }
    public int TotalProcessingTimeMs { get; init; }
    // Source generator attribution
    public string? PredictedSource { get; init; }
    public int SourceConfidence { get; init; }
    // C2PA provenance
    public string? C2paStatus { get; init; }
    public string? C2paIssuer { get; init; }
}

public record MlForensicModule
{
    public string ModuleName { get; init; } = string.Empty;
    public string ModuleLabel { get; init; } = string.Empty;
    public double RiskScore { get; init; }
    public int RiskScore100 { get; init; }
    public string RiskLevel { get; init; } = "Low";
    public List<MlForensicFinding> Findings { get; init; } = [];
    public int ProcessingTimeMs { get; init; }
    public string? Error { get; init; }
}

public record MlForensicFinding
{
    public string Code { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public double RiskScore { get; init; }
    public double Confidence { get; init; }
}

// Agent evaluation (Phase 7)
public record MlAgentEvaluateRequest
{
    public List<Dictionary<string, object>> Damages { get; init; } = [];
    public List<Dictionary<string, object>> ForensicModules { get; init; } = [];
    public double OverallForensicRiskScore { get; init; }
    public string OverallForensicRiskLevel { get; init; } = "Low";
    public decimal CostMin { get; init; }
    public decimal CostMax { get; init; }
    public decimal? GrossTotal { get; init; }
    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public string? VehicleColor { get; init; }
    public string? StructuralIntegrity { get; init; }
    public string? UrgencyLevel { get; init; }
    public bool? IsDriveable { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public string? CaptureTimestamp { get; init; }
    public string? CaptureSource { get; init; }
    public List<string> DamageCauses { get; init; } = [];
}

public record MlAgentReasoningStep
{
    public int Step { get; init; }
    public string Category { get; init; } = "";
    public string Observation { get; init; } = "";
    public string Assessment { get; init; } = "";
    public string Impact { get; init; } = "";
}

public record MlAgentWeatherVerification
{
    public bool Queried { get; init; }
    public bool HadHail { get; init; }
    public bool HadPrecipitation { get; init; }
    public double PrecipitationMm { get; init; }
    public bool? CorroboratesClaim { get; init; }
    public string? DiscrepancyNote { get; init; }
    public string? WeatherDescription { get; init; }
    public string? Error { get; init; }
}

public record MlAgentDecision
{
    public string Outcome { get; init; } = "HumanReview";
    public double Confidence { get; init; }
    public List<MlAgentReasoningStep> ReasoningSteps { get; init; } = [];
    public string? WeatherAssessment { get; init; }
    public List<string> FraudIndicators { get; init; } = [];
    public List<string> RecommendedActions { get; init; } = [];
    public string SummaryHr { get; init; } = "";
    public bool StpEligible { get; init; }
    public List<string> StpBlockers { get; init; } = [];
    public string ModelUsed { get; init; } = "";
    public int ProcessingTimeMs { get; init; }
    public MlAgentWeatherVerification? WeatherVerification { get; init; }
    public bool FallbackUsed { get; init; }
    public string? Error { get; init; }
}

// Evidence timestamp (Phase 8)
public record MlTimestampResult
{
    public bool Success { get; init; }
    public string? TimestampToken { get; init; }
    public string? TimestampedAt { get; init; }
    public string? TsaUrl { get; init; }
    public string? Error { get; init; }
}
