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

    // Owner info (populated for admin queries)
    public string? OwnerEmail { get; init; }
    public string? OwnerFullName { get; init; }

    // User-provided vehicle context
    public string? UserProvidedMake { get; init; }
    public string? UserProvidedModel { get; init; }
    public int? UserProvidedYear { get; init; }
    public int? Mileage { get; init; }

    // Capture metadata (Phase 6)
    public double? CaptureLatitude { get; init; }
    public double? CaptureLongitude { get; init; }
    public double? CaptureGpsAccuracy { get; init; }
    public string? CaptureDeviceInfo { get; init; }
    public string? CaptureSource { get; init; }

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

    // Agent decision (Phase 7)
    public AgentDecisionDto? AgentDecision { get; init; }
    public double? AgentConfidence { get; init; }
    public bool AgentStpEligible { get; init; }
    public bool AgentFallbackUsed { get; init; }
    public int AgentProcessingTimeMs { get; init; }

    // Fraud detection
    public double? FraudRiskScore { get; init; }
    public string? FraudRiskLevel { get; init; }
    public ForensicResultDto? ForensicResult { get; init; }
    public List<ForensicResultDto> FileForensicResults { get; init; } = [];

    // Evidence integrity (Phase 8)
    public string? EvidenceHash { get; init; }
    public List<ImageHashDto>? ImageHashes { get; init; }
    public string? ForensicResultHash { get; init; }
    public string? AgentDecisionHash { get; init; }
    public List<CustodyEventDto>? ChainOfCustody { get; init; }
    public bool HasTimestamp { get; init; }
    public string? TimestampedAt { get; init; }
    public string? TimestampAuthority { get; init; }

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

public record ForensicResultDto
{
    public string? FileName { get; init; }
    public string? FileUrl { get; init; }
    public int SortOrder { get; init; }
    public double OverallRiskScore { get; init; }
    public int OverallRiskScore100 { get; init; }
    public string OverallRiskLevel { get; init; } = "Low";
    public List<ForensicModuleResultDto> Modules { get; init; } = [];
    public string? ElaHeatmapUrl { get; init; }
    public string? FftSpectrumUrl { get; init; }
    public string? SpectralHeatmapUrl { get; init; }
    public int TotalProcessingTimeMs { get; init; }
    // Source generator attribution
    public string? PredictedSource { get; init; }
    public int SourceConfidence { get; init; }
    // C2PA provenance
    public string? C2paStatus { get; init; }
    public string? C2paIssuer { get; init; }
    // 3-class meta-learner probabilities
    public Dictionary<string, double>? VerdictProbabilities { get; init; }
    // PDF page preview image URLs
    public List<string>? PagePreviewUrls { get; init; }
}

public record ForensicModuleResultDto
{
    public string ModuleName { get; init; } = string.Empty;
    public string ModuleLabel { get; init; } = string.Empty;
    public double RiskScore { get; init; }
    public int RiskScore100 { get; init; }
    public string RiskLevel { get; init; } = "Low";
    public List<ForensicFindingDto> Findings { get; init; } = [];
    public int ProcessingTimeMs { get; init; }
    public string? Error { get; init; }
}

public record ForensicFindingDto
{
    public string Code { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public double RiskScore { get; init; }
    public double Confidence { get; init; }
}

public record AgentDecisionDto
{
    public string Outcome { get; init; } = "";
    public double Confidence { get; init; }
    public List<AgentReasoningStepDto> ReasoningSteps { get; init; } = [];
    public string? WeatherAssessment { get; init; }
    public List<string> FraudIndicators { get; init; } = [];
    public List<string> RecommendedActions { get; init; } = [];
    public string SummaryHr { get; init; } = "";
    public bool StpEligible { get; init; }
    public List<string> StpBlockers { get; init; } = [];
    public string ModelUsed { get; init; } = "";
    public int ProcessingTimeMs { get; init; }
    public AgentWeatherVerificationDto? WeatherVerification { get; init; }
}

public record AgentReasoningStepDto
{
    public int Step { get; init; }
    public string Category { get; init; } = "";
    public string Observation { get; init; } = "";
    public string Assessment { get; init; } = "";
    public string Impact { get; init; } = "";
}

public record AgentWeatherVerificationDto
{
    public bool Queried { get; init; }
    public bool HadHail { get; init; }
    public bool HadPrecipitation { get; init; }
    public double PrecipitationMm { get; init; }
    public bool? CorroboratesClaim { get; init; }
    public string? DiscrepancyNote { get; init; }
    public string? WeatherDescription { get; init; }
}

public record ImageHashDto
{
    public string FileName { get; init; } = "";
    public string Sha256 { get; init; } = "";
}

public record CustodyEventDto
{
    public string Event { get; init; } = "";
    public string Timestamp { get; init; } = "";
    public string? Hash { get; init; }
    public string? Details { get; init; }
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

public record AdminStatsDto
{
    // Users
    public int TotalUsers { get; init; }
    public int ActiveUsers { get; init; }
    public int UsersRegisteredToday { get; init; }
    public int UsersRegisteredThisWeek { get; init; }

    // Inspections by status
    public int TotalInspections { get; init; }
    public int CompletedInspections { get; init; }
    public int PendingInspections { get; init; }
    public int AnalyzingInspections { get; init; }
    public int FailedInspections { get; init; }

    // Processing
    public double AverageProcessingTimeMs { get; init; }

    // Queue
    public int QueuePending { get; init; }
    public int QueueActiveUsers { get; init; }

    // Time-series: analyses per day (last 30 days)
    public List<DailyCountDto> AnalysesPerDay { get; init; } = [];

    // Activity: hourly + day-of-week distributions (last 30 days)
    public List<HourlyCountDto> AnalysesPerHour { get; init; } = [];
    public List<DayOfWeekCountDto> AnalysesPerDayOfWeek { get; init; } = [];

    // Distributions
    public Dictionary<string, int> RiskLevelDistribution { get; init; } = [];
    public Dictionary<string, int> VerdictDistribution { get; init; } = [];
    public Dictionary<string, int> DecisionOutcomeDistribution { get; init; } = [];
    public Dictionary<string, int> FileTypeDistribution { get; init; } = [];

    // Recent failures
    public List<AdminFailedInspectionDto> RecentFailures { get; init; } = [];
}

public record DailyCountDto
{
    public string Date { get; init; } = "";
    public int Count { get; init; }
}

public record HourlyCountDto
{
    public int Hour { get; init; }
    public int Count { get; init; }
}

public record DayOfWeekCountDto
{
    public int Day { get; init; }
    public int Count { get; init; }
}

public record AdminFailedInspectionDto
{
    public Guid Id { get; init; }
    public string OriginalFileName { get; init; } = "";
    public string? ErrorMessage { get; init; }
    public string? UserFullName { get; init; }
    public DateTime CreatedAt { get; init; }
}
