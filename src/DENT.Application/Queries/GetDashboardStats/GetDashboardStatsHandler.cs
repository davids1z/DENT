using DENT.Application.Interfaces;
using DENT.Application.Mapping;
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
        var inspections = _db.Inspections.AsQueryable();
        if (request.UserId.HasValue)
            inspections = inspections.Where(i => i.UserId == request.UserId.Value);

        var totalInspections = await inspections.CountAsync(ct);
        var completedInspections = await inspections.CountAsync(i => i.Status == InspectionStatus.Completed, ct);
        var pendingInspections = await inspections.CountAsync(i => i.Status == InspectionStatus.Pending || i.Status == InspectionStatus.Analyzing, ct);

        var completedWithCosts = await inspections
            .Where(i => i.Status == InspectionStatus.Completed && i.TotalEstimatedCostMin.HasValue)
            .ToListAsync(ct);

        var avgCostMin = completedWithCosts.Count > 0 ? completedWithCosts.Average(i => i.TotalEstimatedCostMin!.Value) : 0;
        var avgCostMax = completedWithCosts.Count > 0 ? completedWithCosts.Average(i => i.TotalEstimatedCostMax ?? i.TotalEstimatedCostMin!.Value) : 0;

        var inspectionIds = request.UserId.HasValue
            ? await inspections.Select(i => i.Id).ToListAsync(ct)
            : null;

        var damagesQuery = _db.DamageDetections.AsQueryable();
        if (inspectionIds is not null)
            damagesQuery = damagesQuery.Where(d => inspectionIds.Contains(d.InspectionId));

        var damageTypes = await damagesQuery
            .GroupBy(d => d.DamageType)
            .Select(g => new { Type = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Type, x => x.Count, ct);

        var severities = await damagesQuery
            .GroupBy(d => d.Severity)
            .Select(g => new { Severity = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Severity, x => x.Count, ct);

        var carParts = await damagesQuery
            .GroupBy(d => d.CarPart)
            .Select(g => new { Part = g.Key.ToString(), Count = g.Count() })
            .OrderByDescending(x => x.Count)
            .Take(10)
            .ToDictionaryAsync(x => x.Part, x => x.Count, ct);

        var decisionOutcomes = await inspections
            .Where(i => i.DecisionOutcome != null)
            .GroupBy(i => i.DecisionOutcome!.Value)
            .Select(g => new { Outcome = g.Key.ToString(), Count = g.Count() })
            .ToDictionaryAsync(x => x.Outcome, x => x.Count, ct);

        var recentInspections = await inspections
            .Include(i => i.Damages)
            .Include(i => i.AdditionalImages)
            .Include(i => i.DecisionOverrides)
            .Include(i => i.ForensicResults)
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
            DecisionOutcomeDistribution = decisionOutcomes,
            RecentInspections = recentInspections.Select(InspectionMapper.MapToDto).ToList()
        };
    }
}
