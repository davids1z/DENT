using DENT.Application.Interfaces;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetInspection;

public class GetInspectionHandler : IRequestHandler<GetInspectionQuery, InspectionDto?>
{
    private readonly IDentDbContext _db;

    public GetInspectionHandler(IDentDbContext db) => _db = db;

    public async Task<InspectionDto?> Handle(GetInspectionQuery request, CancellationToken ct)
    {
        var inspection = await _db.Inspections
            .Include(i => i.Damages)
            .AsNoTracking()
            .FirstOrDefaultAsync(i => i.Id == request.Id, ct);

        if (inspection is null) return null;

        return new InspectionDto
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
}
