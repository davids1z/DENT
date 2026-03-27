using DENT.Application.Commands.CreateInspection;
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
            .Include(i => i.AdditionalImages)
            .Include(i => i.DecisionOverrides)
            .Include(i => i.ForensicResults)
            .AsNoTracking()
            .OrderByDescending(i => i.CreatedAt)
            .AsQueryable();

        if (request.UserId.HasValue)
            query = query.Where(i => i.UserId == request.UserId.Value);

        if (!string.IsNullOrEmpty(request.Status) && Enum.TryParse<InspectionStatus>(request.Status, true, out var status))
            query = query.Where(i => i.Status == status);

        var inspections = await query
            .Skip((request.Page - 1) * request.PageSize)
            .Take(request.PageSize)
            .ToListAsync(ct);

        return inspections.Select(CreateInspectionHandler.MapToDto).ToList();
    }
}
