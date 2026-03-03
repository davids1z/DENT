using DENT.Application.Interfaces;
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
        // Upload image to storage
        var imageKey = await _storage.UploadAsync(request.ImageStream, request.FileName, request.ContentType, ct);
        var imageUrl = _storage.GetPublicUrl(imageKey);

        // Create inspection record
        var inspection = new Inspection
        {
            Id = Guid.NewGuid(),
            ImageUrl = imageUrl,
            OriginalFileName = request.FileName,
            Status = InspectionStatus.Analyzing,
            CreatedAt = DateTime.UtcNow
        };

        _db.Inspections.Add(inspection);
        await _db.SaveChangesAsync(ct);

        // Reset stream position for ML analysis
        if (request.ImageStream.CanSeek)
            request.ImageStream.Position = 0;

        // Run ML analysis
        try
        {
            var result = await _mlService.AnalyzeImageAsync(request.ImageStream, request.FileName, ct);

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

                foreach (var damage in result.Damages)
                {
                    inspection.Damages.Add(new DamageDetection
                    {
                        Id = Guid.NewGuid(),
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
                        PartsNeeded = damage.PartsNeeded
                    });
                }
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

    private static InspectionDto MapToDto(Inspection inspection) => new()
    {
        Id = inspection.Id,
        ImageUrl = inspection.ImageUrl,
        OriginalFileName = inspection.OriginalFileName,
        ThumbnailUrl = inspection.ThumbnailUrl,
        Status = inspection.Status.ToString(),
        CreatedAt = inspection.CreatedAt,
        CompletedAt = inspection.CompletedAt,
        VehicleMake = inspection.VehicleMake,
        VehicleModel = inspection.VehicleModel,
        VehicleYear = inspection.VehicleYear,
        VehicleColor = inspection.VehicleColor,
        Summary = inspection.Summary,
        TotalEstimatedCostMin = inspection.TotalEstimatedCostMin,
        TotalEstimatedCostMax = inspection.TotalEstimatedCostMax,
        Currency = inspection.Currency,
        IsDriveable = inspection.IsDriveable,
        UrgencyLevel = inspection.UrgencyLevel,
        ErrorMessage = inspection.ErrorMessage,
        Damages = inspection.Damages.Select(d => new DamageDetectionDto
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
            PartsNeeded = d.PartsNeeded
        }).ToList()
    };
}
