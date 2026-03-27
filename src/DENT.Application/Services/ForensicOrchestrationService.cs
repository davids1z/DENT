using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Application.Models;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

namespace DENT.Application.Services;

public class ForensicOrchestrationService : IForensicOrchestrationService
{
    private readonly IDentDbContext _db;
    private readonly IMlAnalysisService _mlService;
    private readonly IStorageService _storage;
    private readonly IEvidenceService _evidence;
    private readonly IImageProcessingService _imageProcessing;
    private readonly ILogger<ForensicOrchestrationService> _logger;

    public ForensicOrchestrationService(
        IDentDbContext db,
        IMlAnalysisService mlService,
        IStorageService storage,
        IEvidenceService evidence,
        IImageProcessingService imageProcessing,
        ILogger<ForensicOrchestrationService> logger)
    {
        _db = db;
        _mlService = mlService;
        _storage = storage;
        _evidence = evidence;
        _imageProcessing = imageProcessing;
        _logger = logger;
    }

    public async Task RunAnalysisAsync(BackgroundAnalysisData data, CancellationToken ct)
    {
        var inspection = await _db.Inspections
            .Include(i => i.AdditionalImages)
            .FirstOrDefaultAsync(i => i.Id == data.InspectionId, ct);
        if (inspection == null)
        {
            _logger.LogError("Background analysis: inspection {Id} not found", data.InspectionId);
            return;
        }

        var custodyLog = data.CustodyLog;
        var imageHashes = data.ImageHashes;

        try
        {
            // ── Step 1: Run forensics on ALL files ─────────────────────
            MlForensicResult? primaryForensicResult = null;
            ForensicResult? primaryFr = null;
            try
            {
                var filesToAnalyze = new List<(byte[] Data, string FileName, string FileUrl, int SortOrder)>();
                filesToAnalyze.Add((data.FirstImageData, data.FirstImageFileName, inspection.ImageUrl, 0));
                for (int fi = 1; fi < data.AllImages.Count; fi++)
                {
                    var img = data.AllImages[fi];
                    var additionalImg = inspection.AdditionalImages
                        .FirstOrDefault(a => a.OriginalFileName == img.FileName);
                    var fileUrl = additionalImg?.ImageUrl ?? "";
                    filesToAnalyze.Add((img.Data, img.FileName, fileUrl, fi));
                }

                double maxRiskScore = 0;
                string maxRiskLevel = "Low";

                // ── PARALLEL: fire all /forensics HTTP calls simultaneously ──
                // The ML service calls are the bottleneck (~15s each). Running
                // them in parallel means N files complete in ~15s instead of N*15s.
                var forensicTasks = filesToAnalyze.Select(async file =>
                {
                    try
                    {
                        var result = await _mlService.RunForensicsAsync(file.Data, file.FileName, ct);
                        return (file.FileName, file.FileUrl, file.SortOrder, Result: result, Error: (Exception?)null);
                    }
                    catch (Exception ex)
                    {
                        return (file.FileName, file.FileUrl, file.SortOrder, Result: (MlForensicResult?)null, Error: ex);
                    }
                }).ToList();

                var forensicResults = await Task.WhenAll(forensicTasks);

                _logger.LogInformation(
                    "All {Count} forensic analyses completed in parallel for inspection {Id}",
                    forensicResults.Length, inspection.Id);

                // Process results sequentially (heatmap uploads + entity creation are fast)
                foreach (var (fileName, fileUrl, sortOrder, forensicResult, error) in forensicResults)
                {
                    if (error != null || forensicResult == null)
                    {
                        _logger.LogWarning(error,
                            "Forensic analysis failed for file {FileName} in inspection {Id}, continuing",
                            fileName, inspection.Id);
                        continue;
                    }

                    try
                    {
                        string? elaUrl = await UploadHeatmap(forensicResult.ElaHeatmapB64,
                            $"ela_{inspection.Id}_{sortOrder}.png", ct);
                        string? fftUrl = await UploadHeatmap(forensicResult.FftSpectrumB64,
                            $"fft_{inspection.Id}_{sortOrder}.png", ct);
                        string? spectralUrl = await UploadHeatmap(forensicResult.SpectralHeatmapB64,
                            $"spectral_{inspection.Id}_{sortOrder}.png", ct);

                        List<string>? pagePreviewUrls = null;
                        if (forensicResult.PagePreviewsB64 is { Count: > 0 })
                        {
                            pagePreviewUrls = new List<string>();
                            for (int pageNum = 0; pageNum < forensicResult.PagePreviewsB64.Count; pageNum++)
                            {
                                try
                                {
                                    var pageBytes = Convert.FromBase64String(forensicResult.PagePreviewsB64[pageNum]);
                                    using var pageStream = new MemoryStream(pageBytes);
                                    var pageKey = await _storage.UploadAsync(
                                        pageStream, $"page_{inspection.Id}_{sortOrder}_p{pageNum}.jpg", "image/jpeg", ct);
                                    pagePreviewUrls.Add(_storage.GetPublicUrl(pageKey));
                                }
                                catch (Exception ex)
                                {
                                    _logger.LogWarning(ex, "Failed to upload page preview {PageNum}", pageNum);
                                }
                            }
                        }

                        var fr = new ForensicResult
                        {
                            Id = Guid.NewGuid(),
                            InspectionId = inspection.Id,
                            FileName = fileName,
                            FileUrl = fileUrl,
                            SortOrder = sortOrder,
                            OverallRiskScore = forensicResult.OverallRiskScore,
                            OverallRiskScore100 = forensicResult.OverallRiskScore100,
                            OverallRiskLevel = forensicResult.OverallRiskLevel,
                            ModuleResultsJson = JsonSerializer.Serialize(forensicResult.Modules,
                                new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase }),
                            ElaHeatmapUrl = elaUrl,
                            FftSpectrumUrl = fftUrl,
                            SpectralHeatmapUrl = spectralUrl,
                            PredictedSource = forensicResult.PredictedSource,
                            SourceConfidence = forensicResult.SourceConfidence,
                            C2paStatus = forensicResult.C2paStatus,
                            C2paIssuer = forensicResult.C2paIssuer,
                            TotalProcessingTimeMs = forensicResult.TotalProcessingTimeMs,
                            VerdictProbabilitiesJson = forensicResult.VerdictProbabilities != null
                                ? JsonSerializer.Serialize(forensicResult.VerdictProbabilities)
                                : null,
                            PagePreviewUrlsJson = pagePreviewUrls is { Count: > 0 }
                                ? JsonSerializer.Serialize(pagePreviewUrls)
                                : null,
                        };
                        _db.ForensicResults.Add(fr);
                        inspection.ForensicResults.Add(fr);

                        if (sortOrder == 0)
                        {
                            primaryForensicResult = forensicResult;
                            primaryFr = fr;
                        }

                        if (forensicResult.OverallRiskScore > maxRiskScore)
                        {
                            maxRiskScore = forensicResult.OverallRiskScore;
                            maxRiskLevel = forensicResult.OverallRiskLevel;
                        }

                        custodyLog.Add(_evidence.CreateCustodyEvent(
                            "forensics_complete",
                            _evidence.ComputeSha256(fr.ModuleResultsJson ?? "[]"),
                            $"file={fileName}, risk={forensicResult.OverallRiskScore:F2}"));

                        _logger.LogInformation(
                            "Forensics complete for file {FileName} (sort={Sort}): risk={Risk:F2}",
                            fileName, sortOrder, forensicResult.OverallRiskScore);
                    }
                    catch (Exception fileEx)
                    {
                        _logger.LogWarning(fileEx,
                            "Post-processing failed for file {FileName} in inspection {Id}, continuing",
                            fileName, inspection.Id);
                    }
                }

                inspection.FraudRiskScore = maxRiskScore;
                inspection.FraudRiskLevel = Enum.TryParse<FraudRiskLevel>(maxRiskLevel, true, out var frl)
                    ? frl : FraudRiskLevel.Low;

                if (primaryFr != null)
                    inspection.ForensicResultHash = _evidence.ComputeSha256(primaryFr.ModuleResultsJson ?? "[]");
            }
            catch (Exception fex)
            {
                _logger.LogWarning(fex,
                    "Forensic analysis failed for inspection {Id}, continuing without context",
                    inspection.Id);
            }

            // ── Step 2: Skip — Gemini/VLM visual analysis disabled ─────
            MlAnalysisResult result = new MlAnalysisResult { Success = true };

            if (result.Success)
            {
                inspection.Status = InspectionStatus.Completed;
                inspection.CompletedAt = DateTime.UtcNow;
                inspection.VehicleMake = result.VehicleMake;
                inspection.VehicleModel = result.VehicleModel;
                inspection.VehicleYear = result.VehicleYear;
                inspection.VehicleColor = result.VehicleColor;
                inspection.Summary = result.Summary;
                inspection.TotalEstimatedCostMin = result.TotalEstimatedCostMin;
                inspection.TotalEstimatedCostMax = result.TotalEstimatedCostMax;
                inspection.IsDriveable = result.IsDriveable;
                inspection.UrgencyLevel = Enum.TryParse<UrgencyLevel>(result.UrgencyLevel, true, out var ul)
                    ? ul : null;

                // Safety net: override urgency if forensic risk is high
                if (primaryForensicResult != null
                    && primaryForensicResult.OverallRiskScore >= 0.40
                    && (inspection.UrgencyLevel == null || inspection.UrgencyLevel == UrgencyLevel.Low))
                {
                    inspection.UrgencyLevel = primaryForensicResult.OverallRiskScore >= 0.65
                        ? UrgencyLevel.Critical : UrgencyLevel.High;
                    _logger.LogWarning(
                        "Urgency safety net: forensic risk {Risk:F2} overrode ML urgency to {Urgency} for inspection {Id}",
                        primaryForensicResult.OverallRiskScore, inspection.UrgencyLevel, inspection.Id);
                }

                // ── C# SAFETY NET: Summary & finding consistency ─────────
                if (primaryForensicResult != null && primaryForensicResult.OverallRiskScore >= 0.40)
                {
                    ApplySafetyNets(inspection, result, primaryForensicResult);
                }

                inspection.StructuralIntegrity = result.StructuralIntegrity;
                inspection.LaborTotal = result.LaborTotal;
                inspection.PartsTotal = result.PartsTotal;
                inspection.MaterialsTotal = result.MaterialsTotal;
                inspection.GrossTotal = result.GrossTotal;

                PopulateDamages(inspection, result);

                custodyLog.Add(_evidence.CreateCustodyEvent(
                    "analysis_complete",
                    details: $"{inspection.Damages.Count} findings detected"));

                var (ruleOutcome, ruleReason, ruleTraceJson) = DecisionEngine.Evaluate(inspection);

                string agentSummary = "";
                agentSummary = await RunAgentEvaluation(inspection, primaryFr, ruleOutcome, ct);

                inspection.DecisionOutcome = ruleOutcome;
                inspection.DecisionReason = !string.IsNullOrEmpty(agentSummary) ? agentSummary : ruleReason;
                inspection.DecisionTraceJson = ruleTraceJson;

                if (inspection.AgentDecisionJson != null)
                    inspection.AgentDecisionHash = _evidence.ComputeSha256(inspection.AgentDecisionJson);
                custodyLog.Add(_evidence.CreateCustodyEvent(
                    "decision_complete",
                    inspection.AgentDecisionHash,
                    inspection.DecisionOutcome?.ToString()));

                // Evidence chain sealing
                var allHashes = imageHashes
                    .Select(h => (string)((dynamic)h).sha256)
                    .ToList();
                if (inspection.ForensicResultHash != null) allHashes.Add(inspection.ForensicResultHash);
                if (inspection.AgentDecisionHash != null) allHashes.Add(inspection.AgentDecisionHash);
                allHashes.Sort();
                inspection.EvidenceHash = _evidence.ComputeSha256(string.Join(":", allHashes));

                await ObtainTimestamp(inspection, custodyLog, ct);

                inspection.ChainOfCustodyJson = JsonSerializer.Serialize(custodyLog,
                    new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
            }
            else
            {
                inspection.Status = InspectionStatus.Failed;
                inspection.ErrorMessage = result.ErrorMessage;
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Background analysis failed for inspection {Id}", inspection.Id);
            inspection.Status = InspectionStatus.Failed;
            inspection.ErrorMessage = ex.Message;
        }

        await _db.SaveChangesAsync(CancellationToken.None);
    }

    private async Task<string?> UploadHeatmap(string? base64Data, string fileName, CancellationToken ct)
    {
        if (base64Data is null) return null;
        var bytes = Convert.FromBase64String(base64Data);
        using var stream = new MemoryStream(bytes);
        var key = await _storage.UploadAsync(stream, fileName, "image/png", ct);
        return _storage.GetPublicUrl(key);
    }

    private void ApplySafetyNets(Inspection inspection, MlAnalysisResult result, MlForensicResult primaryForensicResult)
    {
        // Summary contradiction check
        var summaryNorm = (inspection.Summary ?? "")
            .Normalize(System.Text.NormalizationForm.FormD);
        summaryNorm = new string(summaryNorm
            .Where(c => System.Globalization.CharUnicodeInfo.GetUnicodeCategory(c)
                != System.Globalization.UnicodeCategory.NonSpacingMark)
            .ToArray()).ToLowerInvariant();

        string[] contradictions = [
            "autenticna", "autenticno", "autenticna fotografija",
            "nema sumnje", "nema manipulacije", "prava fotografija",
            "originalna", "slika je autenticna"
        ];

        if (contradictions.Any(c => summaryNorm.Contains(c)))
        {
            inspection.Summary = $"Forenzicka analiza utvrdila je visoku sumnju na manipulaciju (ukupni rizik: {primaryForensicResult.OverallRiskScore:P0}).";
            _logger.LogWarning("C# safety net: summary contradicted forensics for inspection {Id}, overridden", inspection.Id);
        }

        // Individual damage safety_rating check
        var isCriticalRisk = primaryForensicResult.OverallRiskScore >= 0.75;
        foreach (var dmg in result.Damages)
        {
            if (string.Equals(dmg.SafetyRating, "Safe", StringComparison.OrdinalIgnoreCase))
            {
                dmg.SafetyRating = isCriticalRisk ? "Critical" : "Warning";
                if (string.Equals(dmg.Severity, "Minor", StringComparison.OrdinalIgnoreCase))
                    dmg.Severity = isCriticalRisk ? "Critical"
                        : primaryForensicResult.OverallRiskScore >= 0.65 ? "Severe" : "Moderate";
                _logger.LogWarning("C# safety net: blocked Safe on cause={Cause} for inspection {Id}",
                    dmg.DamageCause, inspection.Id);
            }

            // Block "Autenticno" damage_cause when forensics says high risk
            var causeNorm = (dmg.DamageCause ?? "")
                .Normalize(System.Text.NormalizationForm.FormD);
            causeNorm = new string(causeNorm
                .Where(c => System.Globalization.CharUnicodeInfo.GetUnicodeCategory(c)
                    != System.Globalization.UnicodeCategory.NonSpacingMark)
                .ToArray()).ToLowerInvariant().Trim();

            if (causeNorm is "autenticno" or "autenticna" or "authentic" or "autenticni")
            {
                dmg.DamageCause = _imageProcessing.DeriveForensicCategory(primaryForensicResult);
                dmg.SafetyRating = isCriticalRisk ? "Critical" : "Warning";
                dmg.Severity = isCriticalRisk ? "Critical"
                    : primaryForensicResult.OverallRiskScore >= 0.65 ? "Severe" : "Moderate";
                dmg.Description += " [C# safety net: forenzicki moduli ukazuju na visok rizik manipulacije.]";
                _logger.LogWarning("C# safety net: blocked Autenticno damage_cause for inspection {Id}", inspection.Id);
            }
        }
    }

    private void PopulateDamages(Inspection inspection, MlAnalysisResult result)
    {
        foreach (var damage in result.Damages)
        {
            var lineItemsJson = damage.RepairLineItems.Count > 0
                ? JsonSerializer.Serialize(damage.RepairLineItems.Select(li => new
                {
                    li.LineNumber, li.PartName, li.Operation, li.LaborType,
                    li.LaborHours, li.PartType, li.Quantity, li.UnitCost, li.TotalCost,
                }))
                : null;

            inspection.Damages.Add(new DamageDetection
            {
                InspectionId = inspection.Id,
                DamageType = Enum.TryParse<DamageType>(damage.DamageType, true, out var dt) ? dt : DamageType.Other,
                CarPart = Enum.TryParse<CarPart>(damage.CarPart, true, out var cp) ? cp : CarPart.Other,
                Severity = Enum.TryParse<DamageSeverity>(damage.Severity, true, out var ds) ? ds : DamageSeverity.Moderate,
                Description = damage.Description,
                Confidence = damage.Confidence,
                RepairMethod = damage.RepairMethod,
                EstimatedCostMin = damage.EstimatedCostMin,
                EstimatedCostMax = damage.EstimatedCostMax,
                LaborHours = damage.LaborHours,
                PartsNeeded = damage.PartsNeeded,
                BoundingBox = damage.BoundingBox != null
                    ? JsonSerializer.Serialize(new { x = damage.BoundingBox.X, y = damage.BoundingBox.Y, w = damage.BoundingBox.W, h = damage.BoundingBox.H, imageIndex = damage.BoundingBox.ImageIndex })
                    : null,
                DamageCause = damage.DamageCause,
                SafetyRating = Enum.TryParse<SafetyRating>(damage.SafetyRating, true, out var sr) ? sr : null,
                MaterialType = damage.MaterialType,
                RepairOperations = damage.RepairOperations,
                RepairCategory = Enum.TryParse<RepairCategory>(damage.RepairCategory, true, out var rc) ? rc : null,
                RepairLineItemsJson = lineItemsJson,
            });
        }
    }

    private async Task<string> RunAgentEvaluation(Inspection inspection, ForensicResult? primaryFr, DecisionOutcome ruleOutcome, CancellationToken ct)
    {
        string agentSummary = "";
        try
        {
            var agentRequest = new MlAgentEvaluateRequest
            {
                Damages = inspection.Damages.Select(d => new Dictionary<string, object>
                {
                    ["damageType"] = d.DamageType.ToString(),
                    ["carPart"] = d.CarPart.ToString(),
                    ["severity"] = d.Severity.ToString(),
                    ["description"] = d.Description,
                    ["confidence"] = d.Confidence,
                    ["estimatedCostMin"] = (object)(d.EstimatedCostMin ?? 0m),
                    ["estimatedCostMax"] = (object)(d.EstimatedCostMax ?? 0m),
                    ["safetyRating"] = (object)(d.SafetyRating?.ToString() ?? ""),
                    ["damageCause"] = (object)(d.DamageCause ?? ""),
                    ["repairMethod"] = (object)(d.RepairMethod ?? ""),
                }).ToList(),
                ForensicModules = primaryFr != null
                    ? JsonSerializer.Deserialize<List<Dictionary<string, object>>>(
                        primaryFr.ModuleResultsJson ?? "[]",
                        new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? []
                    : [],
                OverallForensicRiskScore = inspection.FraudRiskScore ?? 0,
                OverallForensicRiskLevel = inspection.FraudRiskLevel?.ToString() ?? "Low",
                CostMin = inspection.TotalEstimatedCostMin ?? 0,
                CostMax = inspection.TotalEstimatedCostMax ?? inspection.GrossTotal ?? 0,
                GrossTotal = inspection.GrossTotal,
                VehicleMake = inspection.VehicleMake,
                VehicleModel = inspection.VehicleModel,
                VehicleYear = inspection.VehicleYear,
                VehicleColor = inspection.VehicleColor,
                StructuralIntegrity = inspection.StructuralIntegrity,
                UrgencyLevel = inspection.UrgencyLevel?.ToString(),
                IsDriveable = inspection.IsDriveable,
                Latitude = inspection.CaptureLatitude,
                Longitude = inspection.CaptureLongitude,
                CaptureTimestamp = inspection.CreatedAt.ToString("o"),
                CaptureSource = inspection.CaptureSource?.ToString(),
                DamageCauses = inspection.Damages
                    .Where(d => !string.IsNullOrEmpty(d.DamageCause))
                    .Select(d => d.DamageCause!)
                    .Distinct()
                    .ToList(),
            };

            var agentResult = await _mlService.RunAgentEvaluationAsync(agentRequest, ct);

            if (agentResult != null && !agentResult.FallbackUsed)
            {
                inspection.AgentDecisionJson = JsonSerializer.Serialize(agentResult,
                    new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
                inspection.AgentConfidence = agentResult.Confidence;
                inspection.AgentWeatherAssessment = agentResult.WeatherAssessment;
                inspection.AgentStpEligible = agentResult.StpEligible;
                inspection.AgentFallbackUsed = false;
                inspection.AgentProcessingTimeMs = agentResult.ProcessingTimeMs;
                agentSummary = agentResult.SummaryHr;
            }
            else
            {
                _logger.LogWarning("Agent returned fallback for inspection {Id}", inspection.Id);
                inspection.AgentFallbackUsed = true;
            }
        }
        catch (Exception agentEx)
        {
            _logger.LogWarning(agentEx, "Agent failed for inspection {Id}, continuing with deterministic decision", inspection.Id);
            inspection.AgentFallbackUsed = true;
        }

        return agentSummary;
    }

    private async Task ObtainTimestamp(Inspection inspection, List<EvidenceCustodyEvent> custodyLog, CancellationToken ct)
    {
        try
        {
            var tsResult = await _mlService.ObtainTimestampAsync(inspection.EvidenceHash!, ct);
            if (tsResult.Success)
            {
                inspection.TimestampToken = tsResult.TimestampToken;
                inspection.TimestampedAt = DateTime.TryParse(tsResult.TimestampedAt, out var tsAt)
                    ? tsAt.ToUniversalTime() : DateTime.UtcNow;
                inspection.TimestampAuthority = tsResult.TsaUrl;
                custodyLog.Add(_evidence.CreateCustodyEvent(
                    "evidence_sealed", inspection.EvidenceHash, $"TSA: {tsResult.TsaUrl}"));
            }
            else
            {
                _logger.LogWarning("Timestamp failed: {Error}", tsResult.Error);
                custodyLog.Add(_evidence.CreateCustodyEvent("timestamp_failed", details: tsResult.Error));
            }
        }
        catch (Exception tsEx)
        {
            _logger.LogWarning(tsEx, "Timestamp call failed for inspection {Id}", inspection.Id);
            custodyLog.Add(_evidence.CreateCustodyEvent("timestamp_failed", details: tsEx.Message));
        }
    }
}
