using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Application.Services;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.Extensions.Logging;

namespace DENT.Application.Commands.CreateInspection;

public class CreateInspectionHandler : IRequestHandler<CreateInspectionCommand, InspectionDto>
{
    private readonly IDentDbContext _db;
    private readonly IStorageService _storage;
    private readonly IMlAnalysisService _mlService;
    private readonly ILogger<CreateInspectionHandler> _logger;

    public CreateInspectionHandler(
        IDentDbContext db,
        IStorageService storage,
        IMlAnalysisService mlService,
        ILogger<CreateInspectionHandler> logger)
    {
        _db = db;
        _storage = storage;
        _mlService = mlService;
        _logger = logger;
    }

    public async Task<InspectionDto> Handle(CreateInspectionCommand request, CancellationToken ct)
    {
        var firstImage = request.Images[0];

        // Upload all images to storage
        string primaryImageUrl;
        using (var stream = new MemoryStream(firstImage.Data))
        {
            var key = await _storage.UploadAsync(stream, firstImage.FileName, firstImage.ContentType, ct);
            primaryImageUrl = _storage.GetPublicUrl(key);
        }

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
        }

        _db.Inspections.Add(inspection);
        await _db.SaveChangesAsync(ct);

        // Run ML analysis
        try
        {
            MlAnalysisResult result;

            if (request.Images.Count == 1)
            {
                // Single image - use original endpoint for backward compat
                using var mlStream = new MemoryStream(firstImage.Data);
                result = await _mlService.AnalyzeImageAsync(mlStream, firstImage.FileName, ct);
            }
            else
            {
                // Multi-image - use new endpoint
                var mlImages = request.Images.Select(img => new MlImageInput
                {
                    Data = img.Data,
                    FileName = img.FileName,
                }).ToList();

                result = await _mlService.AnalyzeMultipleImagesAsync(
                    mlImages,
                    request.VehicleMake, request.VehicleModel, request.VehicleYear, request.Mileage,
                    ct);
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
                            li.LineNumber,
                            li.PartName,
                            li.Operation,
                            li.LaborType,
                            li.LaborHours,
                            li.PartType,
                            li.Quantity,
                            li.UnitCost,
                            li.TotalCost,
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

                // Run decision engine
                var (outcome, reason, traceJson) = DecisionEngine.Evaluate(inspection);
                inspection.DecisionOutcome = outcome;
                inspection.DecisionReason = reason;
                inspection.DecisionTraceJson = traceJson;
            }
            else
            {
                inspection.Status = InspectionStatus.Failed;
                inspection.ErrorMessage = result.ErrorMessage;
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "ML analysis failed for inspection {Id}", inspection.Id);
            inspection.Status = InspectionStatus.Failed;
            inspection.ErrorMessage = ex.Message;
        }

        await _db.SaveChangesAsync(ct);

        return MapToDto(inspection);
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
}
