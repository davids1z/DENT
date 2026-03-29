using System.Text.Json;
using DENT.Domain.Entities;
using DENT.Shared.DTOs;

namespace DENT.Application.Mapping;

public static class InspectionMapper
{
    public static InspectionDto MapToDto(Inspection i) => new()
    {
        Id = i.Id,
        ImageUrl = i.ImageUrl,
        OriginalFileName = i.OriginalFileName,
        ThumbnailUrl = i.ThumbnailUrl,
        Status = i.Status.ToString(),
        OwnerEmail = i.User?.Email,
        OwnerFullName = i.User?.FullName,
        CreatedAt = i.CreatedAt,
        CompletedAt = i.CompletedAt,
        UserProvidedMake = i.UserProvidedMake,
        UserProvidedModel = i.UserProvidedModel,
        UserProvidedYear = i.UserProvidedYear,
        Mileage = i.Mileage,
        CaptureLatitude = i.CaptureLatitude,
        CaptureLongitude = i.CaptureLongitude,
        CaptureGpsAccuracy = i.CaptureGpsAccuracy,
        CaptureDeviceInfo = i.CaptureDeviceInfo,
        CaptureSource = i.CaptureSource?.ToString(),
        VehicleMake = i.VehicleMake,
        VehicleModel = i.VehicleModel,
        VehicleYear = i.VehicleYear,
        VehicleColor = i.VehicleColor,
        Summary = i.Summary,
        TotalEstimatedCostMin = i.TotalEstimatedCostMin,
        TotalEstimatedCostMax = i.TotalEstimatedCostMax,
        Currency = i.Currency,
        IsDriveable = i.IsDriveable,
        UrgencyLevel = i.UrgencyLevel?.ToString(),
        StructuralIntegrity = i.StructuralIntegrity,
        ErrorMessage = i.ErrorMessage,
        LaborTotal = i.LaborTotal,
        PartsTotal = i.PartsTotal,
        MaterialsTotal = i.MaterialsTotal,
        GrossTotal = i.GrossTotal,
        DecisionOutcome = i.DecisionOutcome?.ToString(),
        DecisionReason = i.DecisionReason,
        DecisionTraces = ParseDecisionTraces(i.DecisionTraceJson),
        AgentDecision = ParseAgentDecision(i.AgentDecisionJson),
        AgentConfidence = i.AgentConfidence,
        AgentStpEligible = i.AgentStpEligible,
        AgentFallbackUsed = i.AgentFallbackUsed,
        AgentProcessingTimeMs = i.AgentProcessingTimeMs,
        FraudRiskScore = i.FraudRiskScore,
        FraudRiskLevel = i.FraudRiskLevel?.ToString(),
        ForensicResult = MapForensicResult(i.ForensicResults.OrderBy(f => f.SortOrder).FirstOrDefault()),
        FileForensicResults = i.ForensicResults.OrderBy(f => f.SortOrder).Select(f => MapForensicResult(f)!).ToList(),
        EvidenceHash = i.EvidenceHash,
        ImageHashes = ParseImageHashes(i.ImageHashesJson),
        ForensicResultHash = i.ForensicResultHash,
        AgentDecisionHash = i.AgentDecisionHash,
        ChainOfCustody = ParseChainOfCustody(i.ChainOfCustodyJson),
        HasTimestamp = i.TimestampToken != null,
        TimestampedAt = i.TimestampedAt?.ToString("o"),
        TimestampAuthority = i.TimestampAuthority,
        DecisionOverrides = i.DecisionOverrides.Select(o => new DecisionOverrideDto
        {
            OriginalOutcome = o.OriginalOutcome,
            NewOutcome = o.NewOutcome,
            Reason = o.Reason,
            OperatorName = o.OperatorName,
            CreatedAt = o.CreatedAt,
        }).ToList(),
        AdditionalImages = i.AdditionalImages.OrderBy(img => img.SortOrder).Select(img => new InspectionImageDto
        {
            Id = img.Id,
            ImageUrl = img.ImageUrl,
            OriginalFileName = img.OriginalFileName,
            SortOrder = img.SortOrder,
        }).ToList(),
        Damages = i.Damages.Select(d => new DamageDetectionDto
        {
            Id = d.Id,
            DamageType = d.DamageType.ToString(),
            CarPart = d.CarPart.ToString(),
            Severity = d.Severity.ToString(),
            Description = d.Description,
            Confidence = d.Confidence,
            RepairMethod = d.RepairMethod,
            EstimatedCostMin = d.EstimatedCostMin,
            EstimatedCostMax = d.EstimatedCostMax,
            LaborHours = d.LaborHours,
            PartsNeeded = d.PartsNeeded,
            BoundingBox = d.BoundingBox,
            DamageCause = d.DamageCause,
            SafetyRating = d.SafetyRating?.ToString(),
            MaterialType = d.MaterialType,
            RepairOperations = d.RepairOperations,
            RepairCategory = d.RepairCategory?.ToString(),
            RepairLineItems = ParseRepairLineItems(d.RepairLineItemsJson),
        }).ToList()
    };

    public static ForensicResultDto? MapForensicResult(ForensicResult? fr)
    {
        if (fr == null) return null;
        return new ForensicResultDto
        {
            FileName = fr.FileName,
            FileUrl = fr.FileUrl,
            SortOrder = fr.SortOrder,
            OverallRiskScore = fr.OverallRiskScore,
            OverallRiskScore100 = fr.OverallRiskScore100,
            OverallRiskLevel = fr.OverallRiskLevel,
            Modules = ParseForensicModules(fr.ModuleResultsJson),
            ElaHeatmapUrl = fr.ElaHeatmapUrl,
            FftSpectrumUrl = fr.FftSpectrumUrl,
            SpectralHeatmapUrl = fr.SpectralHeatmapUrl,
            TotalProcessingTimeMs = fr.TotalProcessingTimeMs,
            PredictedSource = fr.PredictedSource,
            SourceConfidence = fr.SourceConfidence,
            C2paStatus = fr.C2paStatus,
            C2paIssuer = fr.C2paIssuer,
            VerdictProbabilities = ParseVerdictProbabilities(fr.VerdictProbabilitiesJson),
            PagePreviewUrls = ParsePagePreviewUrls(fr.PagePreviewUrlsJson),
        };
    }

    public static List<DecisionTraceEntryDto> ParseDecisionTraces(string? json)
    {
        if (string.IsNullOrEmpty(json)) return [];
        try
        {
            return JsonSerializer.Deserialize<List<DecisionTraceEntryDto>>(json, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                PropertyNameCaseInsensitive = true,
            }) ?? [];
        }
        catch { return []; }
    }

    public static List<string>? ParsePagePreviewUrls(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return null;
        try { return JsonSerializer.Deserialize<List<string>>(json); }
        catch { return null; }
    }

    public static Dictionary<string, double>? ParseVerdictProbabilities(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try { return JsonSerializer.Deserialize<Dictionary<string, double>>(json); }
        catch { return null; }
    }

    public static AgentDecisionDto? ParseAgentDecision(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            return JsonSerializer.Deserialize<AgentDecisionDto>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
        }
        catch { return null; }
    }

    public static List<ForensicModuleResultDto> ParseForensicModules(string? json)
    {
        if (string.IsNullOrEmpty(json)) return [];
        try
        {
            return JsonSerializer.Deserialize<List<ForensicModuleResultDto>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            }) ?? [];
        }
        catch { return []; }
    }

    public static List<RepairLineItemDto> ParseRepairLineItems(string? json)
    {
        if (string.IsNullOrEmpty(json)) return [];
        try
        {
            return JsonSerializer.Deserialize<List<RepairLineItemDto>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            }) ?? [];
        }
        catch { return []; }
    }

    public static List<ImageHashDto>? ParseImageHashes(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            return JsonSerializer.Deserialize<List<ImageHashDto>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
        }
        catch { return null; }
    }

    public static List<CustodyEventDto>? ParseChainOfCustody(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            return JsonSerializer.Deserialize<List<CustodyEventDto>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
        }
        catch { return null; }
    }
}
