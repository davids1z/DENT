using DENT.Application.Interfaces;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetInspections;

public class GetInspectionsHandler : IRequestHandler<GetInspectionsQuery, List<InspectionDto>>
{
    private readonly IDentDbContext _db;

    public GetInspectionsHandler(IDentDbContext db) => _db = db;

    public async Task<List<InspectionDto>> Handle(GetInspectionsQuery request, CancellationToken ct)
    {
        var query = _db.Inspections
            .Include(i => i.Damages)
            .AsNoTracking()
            .OrderByDescending(i => i.CreatedAt)
            .AsQueryable();

        if (!string.IsNullOrEmpty(request.Status) && Enum.TryParse<InspectionStatus>(request.Status, true, out var status))
            query = query.Where(i => i.Status == status);

        var inspections = await query
            .Skip((request.Page - 1) * request.PageSize)
            .Take(request.PageSize)
            .ToListAsync(ct);

        return inspections.Select(i => new InspectionDto
        {
            Id = i.Id,
            ImageUrl = i.ImageUrl,
            OriginalFileName = i.OriginalFileName,
            ThumbnailUrl = i.ThumbnailUrl,
            Status = i.Status.ToString(),
            CreatedAt = i.CreatedAt,
            CompletedAt = i.CompletedAt,
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
            ErrorMessage = i.ErrorMessage,
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
                PartsNeeded = d.PartsNeeded
            }).ToList()
        }).ToList();
    }
}
