using DENT.Application.Interfaces;
using DENT.Application.Mapping;
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
        var query = _db.Inspections
            .Include(i => i.Damages)
            .Include(i => i.AdditionalImages)
            .Include(i => i.DecisionOverrides)
            .Include(i => i.ForensicResults)
            .AsNoTracking()
            .AsQueryable();

        if (request.UserId.HasValue)
            query = query.Where(i => i.UserId == request.UserId.Value);

        var inspection = await query.FirstOrDefaultAsync(i => i.Id == request.Id, ct);
        if (inspection is null) return null;

        return InspectionMapper.MapToDto(inspection);
    }
}
