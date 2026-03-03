using DENT.Application.Interfaces;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetDashboardStats;

public class GetDashboardStatsHandler : IRequestHandler<GetDashboardStatsQuery, DashboardStatsDto>
{
    private readonly IDentDbContext _db;

    public GetDashboardStatsHandler(IDentDbContext db) => _db = db;

    public async Task<DashboardStatsDto> Handle(GetDashboardStatsQuery request, CancellationToken ct)
    {
        var totalInspections = await _db.Inspections.CountAsync(ct);
        var completedInspections = await _db.Inspections.CountAsync(i => i.Status == InspectionStatus.Completed, ct);
        var pendingInspections = await _db.Inspections.CountAsync(i => i.Status == InspectionStatus.Pending || i.Status == InspectionStatus.Analyzing, ct);

        var completedWithCosts = await _db.Inspections
            .Where(i => i.Status == InspectionStatus.Completed && i.TotalEstimatedCostMin.HasValue)
            .ToListAsync(ct);

        var avgCostMin = completedWithCosts.Count > 0 ? completedWithCosts.Average(i => i.TotalEstimatedCostMin!.Value) : 0;
        var avgCostMax = completedWithCosts.Count > 0 ? completedWithCosts.Average(i => i.TotalEstimatedCostMax ?? i.TotalEstimatedCostMin!.Value) : 0;

        var damageTypes = await _db.DamageDetections
            .GroupBy(d => d.DamageType)
            .Select(g => new { Type = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Type, x => x.Count, ct);

        var severities = await _db.DamageDetections
            .GroupBy(d => d.Severity)
            .Select(g => new { Severity = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Severity, x => x.Count, ct);

        var carParts = await _db.DamageDetections
            .GroupBy(d => d.CarPart)
            .Select(g => new { Part = g.Key.ToString(), Count = g.Count() })
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToDictionaryAsync(x => x.Part, x => x.Count, ct);

        var recentInspections = await _db.Inspections
            .Include(i => i.Damages)
            .AsNoTracking()
            .OrderByDescending(i => i.CreatedAt)
            .Take(5)
            .ToListAsync(ct);

        return new DashboardStatsDto
        {
            TotalInspections = totalInspections,
            CompletedInspections = completedInspections,
            PendingInspections = pendingInspections,
            AverageCostMin = Math.Round(avgCostMin, 2),
            AverageCostMax = Math.Round(avgCostMax, 2),
            DamageTypeDistribution = damageTypes,
            SeverityDistribution = severities,
            CarPartDistribution = carParts,
            RecentInspections = recentInspections.Select(i => new InspectionDto
            {
                Id = i.Id,
                ImageUrl = i.ImageUrl,
                OriginalFileName = i.OriginalFileName,
                Status = i.Status.ToString(),
                CreatedAt = i.CreatedAt,
                CompletedAt = i.CompletedAt,
                VehicleMake = i.VehicleMake,
                VehicleModel = i.VehicleModel,
                Summary = i.Summary,
                TotalEstimatedCostMin = i.TotalEstimatedCostMin,
                TotalEstimatedCostMax = i.TotalEstimatedCostMax,
                Currency = i.Currency,
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
            }).ToList()
        };
    }
}
