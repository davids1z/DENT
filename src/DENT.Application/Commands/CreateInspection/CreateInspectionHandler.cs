using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace DENT.Application.Commands.CreateInspection;

public class CreateInspectionHandler : IRequestHandler<CreateInspectionCommand, InspectionDto>
{
    private readonly IDentDbContext _db;
    private readonly IStorageService _storage;
    private readonly IMlAnalysisService _mlService;
    private readonly ILogger<CreateInspectionHandler> _logger;
    private readonly IServiceScopeFactory _scopeFactory;

    public CreateInspectionHandler(
        IDentDbContext db,
        IStorageService storage,
        IMlAnalysisService mlService,
        ILogger<CreateInspectionHandler> logger,
        IServiceScopeFactory scopeFactory)
    {
        _db = db;
        _storage = storage;
        _mlService = mlService;
        _logger = logger;
        _scopeFactory = scopeFactory;
    }

    public async Task<InspectionDto> Handle(CreateInspectionCommand request, CancellationToken ct)
    {
        var firstImage = request.Images[0];

        // Evidence tracking (Phase 8)
        var imageHashes = new List<object>();
        var custodyLog = new List<EvidenceCustodyEvent>();

        // Upload all images to storage
        string primaryImageUrl;
        using (var stream = new MemoryStream(firstImage.Data))
        {
            var key = await _storage.UploadAsync(stream, firstImage.FileName, firstImage.ContentType, ct);
            primaryImageUrl = _storage.GetPublicUrl(key);
        }

        // Hash primary image
        var primaryHash = ComputeSha256(firstImage.Data);
        imageHashes.Add(new { fileName = firstImage.FileName, sha256 = primaryHash });
        custodyLog.Add(new EvidenceCustodyEvent
        {
            Event = "image_received",
            Timestamp = DateTime.UtcNow,
            Hash = primaryHash,
            Details = firstImage.FileName,
        });

        // Create inspection record
        var inspection = new Inspection
        {
            Id = Guid.NewGuid(),
            ImageUrl = primaryImageUrl,
            OriginalFileName = firstImage.FileName,
            Status = InspectionStatus.Analyzing,
            CreatedAt = DateTime.UtcNow,
            UserProvidedMake = request.VehicleMake,
            UserProvidedModel = request.VehicleModel,
            UserProvidedYear = request.VehicleYear,
            Mileage = request.Mileage,
        };

        // Parse capture metadata (Phase 6)
        if (!string.IsNullOrEmpty(request.CaptureMetadataJson))
        {
            try
            {
                var meta = JsonSerializer.Deserialize<List<CaptureMetaItem>>(
                    request.CaptureMetadataJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

                if (meta is { Count: > 0 })
                {
                    inspection.CaptureSource = "camera";
                    var first = meta[0];
                    if (first.Gps is not null)
                    {
                        inspection.CaptureLatitude = first.Gps.Latitude;
                        inspection.CaptureLongitude = first.Gps.Longitude;
                        inspection.CaptureGpsAccuracy = first.Gps.Accuracy;
                    }
                    if (first.Device is not null)
                    {
                        inspection.CaptureDeviceInfo = JsonSerializer.Serialize(first.Device,
                            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to parse capture metadata, continuing without");
            }
        }
        else
        {
            inspection.CaptureSource = "upload";
        }

        // Upload additional images
        for (int i = 1; i < request.Images.Count; i++)
        {
            var img = request.Images[i];
            using var stream = new MemoryStream(img.Data);
            var key = await _storage.UploadAsync(stream, img.FileName, img.ContentType, ct);
            var url = _storage.GetPublicUrl(key);
            inspection.AdditionalImages.Add(new InspectionImage
            {
                Id = Guid.NewGuid(),
                InspectionId = inspection.Id,
                ImageUrl = url,
                OriginalFileName = img.FileName,
                SortOrder = i,
                CreatedAt = DateTime.UtcNow,
            });

            // Hash additional image
            var imgHash = ComputeSha256(img.Data);
            imageHashes.Add(new { fileName = img.FileName, sha256 = imgHash });
            custodyLog.Add(new EvidenceCustodyEvent
            {
                Event = "image_received",
                Timestamp = DateTime.UtcNow,
                Hash = imgHash,
                Details = img.FileName,
            });
        }

        inspection.ImageHashesJson = JsonSerializer.Serialize(imageHashes);

        _db.Inspections.Add(inspection);
        await _db.SaveChangesAsync(CancellationToken.None);

        // ── Return immediately, process analysis in background ──────
        // The analysis pipeline takes 60-120s which exceeds Cloudflare's
        // ~100s timeout. By returning the inspection ID immediately, the
        // frontend can poll GET /api/inspections/{id} for completion.
        var backgroundData = new BackgroundAnalysisData
        {
            InspectionId = inspection.Id,
            FirstImageData = firstImage.Data,
            FirstImageFileName = firstImage.FileName,
            AllImages = request.Images,
            CaptureSource = inspection.CaptureSource,
            VehicleMake = request.VehicleMake,
            VehicleModel = request.VehicleModel,
            VehicleYear = request.VehicleYear,
            Mileage = request.Mileage,
            ImageHashes = imageHashes,
            CustodyLog = custodyLog,
        };

        _ = Task.Run(() => RunAnalysisInBackground(backgroundData));

        return MapToDto(inspection);
    }

    private async Task RunAnalysisInBackground(BackgroundAnalysisData data)
    {
        using var scope = _scopeFactory.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<IDentDbContext>();
        var mlService = scope.ServiceProvider.GetRequiredService<IMlAnalysisService>();
        var storage = scope.ServiceProvider.GetRequiredService<IStorageService>();
        var logger = scope.ServiceProvider.GetRequiredService<ILogger<CreateInspectionHandler>>();

        var inspection = await db.Inspections.FindAsync(data.InspectionId);
        if (inspection == null)
        {
            logger.LogError("Background analysis: inspection {Id} not found", data.InspectionId);
            return;
        }

        var custodyLog = data.CustodyLog;
        var imageHashes = data.ImageHashes;

        try
        {
            // ── Step 1: Run forensics ───────────────────────────────────
            MlForensicResult? forensicResult = null;
            try
            {
                forensicResult = await mlService.RunForensicsAsync(
                    data.FirstImageData, data.FirstImageFileName, CancellationToken.None);

                string? elaUrl = null;
                if (forensicResult.ElaHeatmapB64 is not null)
                {
                    var elaBytes = Convert.FromBase64String(forensicResult.ElaHeatmapB64);
                    using var elaStream = new MemoryStream(elaBytes);
                    var elaKey = await storage.UploadAsync(
                        elaStream, $"ela_{inspection.Id}.png", "image/png", CancellationToken.None);
                    elaUrl = storage.GetPublicUrl(elaKey);
                }

                string? fftUrl = null;
                if (forensicResult.FftSpectrumB64 is not null)
                {
                    var fftBytes = Convert.FromBase64String(forensicResult.FftSpectrumB64);
                    using var fftStream = new MemoryStream(fftBytes);
                    var fftKey = await storage.UploadAsync(
                        fftStream, $"fft_{inspection.Id}.png", "image/png", CancellationToken.None);
                    fftUrl = storage.GetPublicUrl(fftKey);
                }

                string? spectralUrl = null;
                if (forensicResult.SpectralHeatmapB64 is not null)
                {
                    var spectralBytes = Convert.FromBase64String(forensicResult.SpectralHeatmapB64);
                    using var spectralStream = new MemoryStream(spectralBytes);
                    var spectralKey = await storage.UploadAsync(
                        spectralStream, $"spectral_{inspection.Id}.png", "image/png", CancellationToken.None);
                    spectralUrl = storage.GetPublicUrl(spectralKey);
                }

                inspection.FraudRiskScore = forensicResult.OverallRiskScore;
                inspection.FraudRiskLevel = forensicResult.OverallRiskLevel;

                var fr = new ForensicResult
                {
                    Id = Guid.NewGuid(),
                    InspectionId = inspection.Id,
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
                };
                db.ForensicResults.Add(fr);
                inspection.ForensicResult = fr;

                var forensicJson = fr.ModuleResultsJson ?? "[]";
                inspection.ForensicResultHash = ComputeSha256(forensicJson);
                custodyLog.Add(new EvidenceCustodyEvent
                {
                    Event = "forensics_complete",
                    Timestamp = DateTime.UtcNow,
                    Hash = inspection.ForensicResultHash,
                    Details = $"risk={inspection.FraudRiskScore:F2}",
                });
            }
            catch (Exception fex)
            {
                logger.LogWarning(fex,
                    "Forensic analysis failed for inspection {Id}, continuing without context",
                    inspection.Id);
            }

            // ── Step 2: Run AI visual analysis (images only) ──────────
            // Documents (PDF, DOCX, XLSX) are fully analyzed by forensics
            // in Step 1 — no need for Gemini/VLM visual analysis.
            var docExtensions = new[] { ".pdf", ".docx", ".xlsx", ".xls", ".doc" };
            var isDocument = docExtensions.Any(ext =>
                data.FirstImageFileName.EndsWith(ext, StringComparison.OrdinalIgnoreCase));

            MlAnalysisResult result;
            if (isDocument)
            {
                // Documents: skip visual analysis, use forensic results directly
                result = new MlAnalysisResult { Success = true };
                logger.LogInformation("Document detected ({FileName}), skipping visual analysis",
                    data.FirstImageFileName);
            }
            else if (forensicResult != null && data.AllImages.Count == 1)
            {
                result = await mlService.AnalyzeImageWithContextAsync(
                    data.FirstImageData, data.FirstImageFileName, forensicResult,
                    data.CaptureSource, CancellationToken.None);
            }
            else if (data.AllImages.Count == 1)
            {
                using var mlStream = new MemoryStream(data.FirstImageData);
                result = await mlService.AnalyzeImageAsync(mlStream, data.FirstImageFileName, CancellationToken.None);
            }
            else
            {
                var mlImages = data.AllImages.Select(img => new MlImageInput
                {
                    Data = img.Data,
                    FileName = img.FileName,
                }).ToList();
                result = await mlService.AnalyzeMultipleImagesAsync(
                    mlImages,
                    data.VehicleMake, data.VehicleModel, data.VehicleYear, data.Mileage,
                    CancellationToken.None);
            }

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
                inspection.UrgencyLevel = result.UrgencyLevel;

                // Safety net: override urgency if forensic risk is high
                if (forensicResult != null
                    && forensicResult.OverallRiskScore >= 0.40
                    && (inspection.UrgencyLevel == null || inspection.UrgencyLevel == "Low"))
                {
                    inspection.UrgencyLevel = forensicResult.OverallRiskScore >= 0.65
                        ? "Critical" : "High";
                    logger.LogWarning(
                        "Urgency safety net: forensic risk {Risk:F2} overrode ML urgency to {Urgency} for inspection {Id}",
                        forensicResult.OverallRiskScore, inspection.UrgencyLevel, inspection.Id);
                }

                // ── C# SAFETY NET: Summary & finding consistency ─────────
                // Defence-in-depth: even after Python enforcement, verify that
                // the summary and individual findings don't contradict forensics.
                if (forensicResult != null && forensicResult.OverallRiskScore >= 0.40)
                {
                    // Summary contradiction check (normalize: strip diacritics + lowercase)
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
                        inspection.Summary = $"Forenzicka analiza utvrdila je visoku sumnju na manipulaciju (ukupni rizik: {forensicResult.OverallRiskScore:P0}).";
                        logger.LogWarning(
                            "C# safety net: summary contradicted forensics for inspection {Id}, overridden",
                            inspection.Id);
                    }

                    // Individual damage safety_rating check
                    var isCriticalRisk = forensicResult.OverallRiskScore >= 0.75;
                    foreach (var dmg in result.Damages)
                    {
                        if (string.Equals(dmg.SafetyRating, "Safe", StringComparison.OrdinalIgnoreCase))
                        {
                            dmg.SafetyRating = isCriticalRisk ? "Critical" : "Warning";
                            if (string.Equals(dmg.Severity, "Minor", StringComparison.OrdinalIgnoreCase))
                                dmg.Severity = isCriticalRisk ? "Critical"
                                    : forensicResult.OverallRiskScore >= 0.65 ? "Severe" : "Moderate";
                            logger.LogWarning(
                                "C# safety net: blocked Safe on cause={Cause} for inspection {Id}",
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
                            dmg.DamageCause = DeriveForensicCategory(forensicResult);
                            dmg.SafetyRating = isCriticalRisk ? "Critical" : "Warning";
                            dmg.Severity = isCriticalRisk ? "Critical"
                                : forensicResult.OverallRiskScore >= 0.65 ? "Severe" : "Moderate";
                            dmg.Description += " [C# safety net: forenzicki moduli ukazuju na visok rizik manipulacije.]";
                            logger.LogWarning(
                                "C# safety net: blocked Autenticno damage_cause for inspection {Id}",
                                inspection.Id);
                        }
                    }
                }

                inspection.StructuralIntegrity = result.StructuralIntegrity;
                inspection.LaborTotal = result.LaborTotal;
                inspection.PartsTotal = result.PartsTotal;
                inspection.MaterialsTotal = result.MaterialsTotal;
                inspection.GrossTotal = result.GrossTotal;

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
                        SafetyRating = damage.SafetyRating,
                        MaterialType = damage.MaterialType,
                        RepairOperations = damage.RepairOperations,
                        RepairCategory = damage.RepairCategory,
                        RepairLineItemsJson = lineItemsJson,
                    });
                }

                custodyLog.Add(new EvidenceCustodyEvent
                {
                    Event = "analysis_complete",
                    Timestamp = DateTime.UtcNow,
                    Details = $"{inspection.Damages.Count} findings detected",
                });

                var (ruleOutcome, ruleReason, ruleTraceJson) = DecisionEngine.Evaluate(inspection);

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
                            ["safetyRating"] = (object)(d.SafetyRating ?? ""),
                            ["damageCause"] = (object)(d.DamageCause ?? ""),
                            ["repairMethod"] = (object)(d.RepairMethod ?? ""),
                        }).ToList(),
                        ForensicModules = inspection.ForensicResult != null
                            ? JsonSerializer.Deserialize<List<Dictionary<string, object>>>(
                                inspection.ForensicResult.ModuleResultsJson ?? "[]",
                                new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? []
                            : [],
                        OverallForensicRiskScore = inspection.FraudRiskScore ?? 0,
                        OverallForensicRiskLevel = inspection.FraudRiskLevel ?? "Low",
                        CostMin = inspection.TotalEstimatedCostMin ?? 0,
                        CostMax = inspection.TotalEstimatedCostMax ?? inspection.GrossTotal ?? 0,
                        GrossTotal = inspection.GrossTotal,
                        VehicleMake = inspection.VehicleMake,
                        VehicleModel = inspection.VehicleModel,
                        VehicleYear = inspection.VehicleYear,
                        VehicleColor = inspection.VehicleColor,
                        StructuralIntegrity = inspection.StructuralIntegrity,
                        UrgencyLevel = inspection.UrgencyLevel,
                        IsDriveable = inspection.IsDriveable,
                        Latitude = inspection.CaptureLatitude,
                        Longitude = inspection.CaptureLongitude,
                        CaptureTimestamp = inspection.CreatedAt.ToString("o"),
                        CaptureSource = inspection.CaptureSource,
                        DamageCauses = inspection.Damages
                            .Where(d => !string.IsNullOrEmpty(d.DamageCause))
                            .Select(d => d.DamageCause!)
                            .Distinct()
                            .ToList(),
                    };

                    var agentResult = await mlService.RunAgentEvaluationAsync(agentRequest, CancellationToken.None);

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
                        logger.LogWarning("Agent returned fallback for inspection {Id}", inspection.Id);
                        inspection.AgentFallbackUsed = true;
                    }
                }
                catch (Exception agentEx)
                {
                    logger.LogWarning(agentEx, "Agent failed for inspection {Id}, continuing with deterministic decision", inspection.Id);
                    inspection.AgentFallbackUsed = true;
                }

                inspection.DecisionOutcome = ruleOutcome;
                inspection.DecisionReason = !string.IsNullOrEmpty(agentSummary) ? agentSummary : ruleReason;
                inspection.DecisionTraceJson = ruleTraceJson;

                if (inspection.AgentDecisionJson != null)
                    inspection.AgentDecisionHash = ComputeSha256(inspection.AgentDecisionJson);
                custodyLog.Add(new EvidenceCustodyEvent
                {
                    Event = "decision_complete",
                    Timestamp = DateTime.UtcNow,
                    Hash = inspection.AgentDecisionHash,
                    Details = inspection.DecisionOutcome,
                });

                var allHashes = imageHashes
                    .Select(h => (string)((dynamic)h).sha256)
                    .ToList();
                if (inspection.ForensicResultHash != null) allHashes.Add(inspection.ForensicResultHash);
                if (inspection.AgentDecisionHash != null) allHashes.Add(inspection.AgentDecisionHash);
                allHashes.Sort();
                inspection.EvidenceHash = ComputeSha256(string.Join(":", allHashes));

                try
                {
                    var tsResult = await mlService.ObtainTimestampAsync(inspection.EvidenceHash, CancellationToken.None);
                    if (tsResult.Success)
                    {
                        inspection.TimestampToken = tsResult.TimestampToken;
                        inspection.TimestampedAt = DateTime.TryParse(tsResult.TimestampedAt, out var tsAt)
                            ? tsAt.ToUniversalTime() : DateTime.UtcNow;
                        inspection.TimestampAuthority = tsResult.TsaUrl;
                        custodyLog.Add(new EvidenceCustodyEvent
                        {
                            Event = "evidence_sealed",
                            Timestamp = DateTime.UtcNow,
                            Hash = inspection.EvidenceHash,
                            Details = $"TSA: {tsResult.TsaUrl}",
                        });
                    }
                    else
                    {
                        logger.LogWarning("Timestamp failed: {Error}", tsResult.Error);
                        custodyLog.Add(new EvidenceCustodyEvent
                        {
                            Event = "timestamp_failed",
                            Timestamp = DateTime.UtcNow,
                            Details = tsResult.Error,
                        });
                    }
                }
                catch (Exception tsEx)
                {
                    logger.LogWarning(tsEx, "Timestamp call failed for inspection {Id}", inspection.Id);
                    custodyLog.Add(new EvidenceCustodyEvent
                    {
                        Event = "timestamp_failed",
                        Timestamp = DateTime.UtcNow,
                        Details = tsEx.Message,
                    });
                }

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
            logger.LogError(ex, "Background analysis failed for inspection {Id}", inspection.Id);
            inspection.Status = InspectionStatus.Failed;
            inspection.ErrorMessage = ex.Message;
        }

        await db.SaveChangesAsync(CancellationToken.None);
    }

    internal static InspectionDto MapToDto(Inspection i) => new()
    {
        Id = i.Id,
        ImageUrl = i.ImageUrl,
        OriginalFileName = i.OriginalFileName,
        ThumbnailUrl = i.ThumbnailUrl,
        Status = i.Status.ToString(),
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
        CaptureSource = i.CaptureSource,
        VehicleMake = i.VehicleMake,
        VehicleModel = i.VehicleModel,
        VehicleYear = i.VehicleYear,
        VehicleColor = i.VehicleColor,
        Summary = i.Summary,
        TotalEstimatedCostMin = i.TotalEstimatedCostMin,
        TotalEstimatedCostMax = i.TotalEstimatedCostMax,
        Currency = i.Currency,
        IsDriveable = i.IsDriveable,
        UrgencyLevel = i.UrgencyLevel,
        StructuralIntegrity = i.StructuralIntegrity,
        ErrorMessage = i.ErrorMessage,
        LaborTotal = i.LaborTotal,
        PartsTotal = i.PartsTotal,
        MaterialsTotal = i.MaterialsTotal,
        GrossTotal = i.GrossTotal,
        DecisionOutcome = i.DecisionOutcome,
        DecisionReason = i.DecisionReason,
        DecisionTraces = ParseDecisionTraces(i.DecisionTraceJson),
        AgentDecision = ParseAgentDecision(i.AgentDecisionJson),
        AgentConfidence = i.AgentConfidence,
        AgentStpEligible = i.AgentStpEligible,
        AgentFallbackUsed = i.AgentFallbackUsed,
        AgentProcessingTimeMs = i.AgentProcessingTimeMs,
        FraudRiskScore = i.FraudRiskScore,
        FraudRiskLevel = i.FraudRiskLevel,
        ForensicResult = MapForensicResult(i.ForensicResult),
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
            SafetyRating = d.SafetyRating,
            MaterialType = d.MaterialType,
            RepairOperations = d.RepairOperations,
            RepairCategory = d.RepairCategory,
            RepairLineItems = ParseRepairLineItems(d.RepairLineItemsJson),
        }).ToList()
    };

    private static List<DecisionTraceEntryDto> ParseDecisionTraces(string? json)
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

    private static ForensicResultDto? MapForensicResult(ForensicResult? fr)
    {
        if (fr == null) return null;
        return new ForensicResultDto
        {
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
        };
    }

    private static Dictionary<string, double>? ParseVerdictProbabilities(string? json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, double>>(json);
        }
        catch
        {
            return null;
        }
    }

    private static AgentDecisionDto? ParseAgentDecision(string? json)
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

    private static List<ForensicModuleResultDto> ParseForensicModules(string? json)
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

    internal static List<RepairLineItemDto> ParseRepairLineItems(string? json)
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

    internal static List<ImageHashDto>? ParseImageHashes(string? json)
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

    internal static List<CustodyEventDto>? ParseChainOfCustody(string? json)
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

    private static string ComputeSha256(byte[] data)
    {
        var hash = SHA256.HashData(data);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string ComputeSha256(string text)
    {
        return ComputeSha256(Encoding.UTF8.GetBytes(text));
    }

    /// <summary>
    /// Derive a forensic category label from the highest-risk forensic module,
    /// instead of using the generic "Metadata anomalija" fallback.
    /// </summary>
    private static string DeriveForensicCategory(MlForensicResult forensicResult)
    {
        var categoryMap = new Dictionary<string, string>
        {
            ["ai_generation_detection"] = "AI generiranje",
            ["clip_ai_detection"] = "AI generiranje",
            ["vae_reconstruction"] = "AI generiranje",
            ["modification_detection"] = "Digitalna manipulacija",
            ["deep_modification_detection"] = "Digitalna manipulacija",
            ["spectral_forensics"] = "Spektralna anomalija",
            ["prnu_detection"] = "Sumnjiva tekstura",
            ["semantic_forensics"] = "Perspektivna anomalija",
            ["metadata_analysis"] = "Metadata anomalija",
        };

        var topModule = forensicResult.Modules
            .Where(m => m.RiskScore >= 0.40)
            .OrderByDescending(m => m.RiskScore)
            .FirstOrDefault();

        if (topModule != null && categoryMap.TryGetValue(topModule.ModuleName, out var category))
            return category;

        return "Metadata anomalija";
    }
}

// Capture metadata DTOs (Phase 6)
internal record CaptureMetaItem
{
    public GpsData? Gps { get; init; }
    public DeviceData? Device { get; init; }
    public string? CapturedAt { get; init; }
}

internal record GpsData
{
    public double Latitude { get; init; }
    public double Longitude { get; init; }
    public double Accuracy { get; init; }
}

internal record DeviceData
{
    public string? UserAgent { get; init; }
    public string? CameraLabel { get; init; }
    public int ScreenWidth { get; init; }
    public int ScreenHeight { get; init; }
    public string? CaptureTimestamp { get; init; }
}

// Background analysis data (carried from handler to background task)
internal record BackgroundAnalysisData
{
    public Guid InspectionId { get; init; }
    public byte[] FirstImageData { get; init; } = [];
    public string FirstImageFileName { get; init; } = "";
    public List<ImageInput> AllImages { get; init; } = [];
    public string? CaptureSource { get; init; }
    public string? VehicleMake { get; init; }
    public string? VehicleModel { get; init; }
    public int? VehicleYear { get; init; }
    public int? Mileage { get; init; }
    public List<object> ImageHashes { get; init; } = [];
    public List<EvidenceCustodyEvent> CustodyLog { get; init; } = [];
}

// Evidence chain of custody (Phase 8)
internal record EvidenceCustodyEvent
{
    public string Event { get; init; } = "";
    public DateTime Timestamp { get; init; }
    public string? Hash { get; init; }
    public string? Details { get; init; }
}
