using DENT.Application.Interfaces;
using DENT.Application.Mapping;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Commands.OverrideDecision;

public class OverrideDecisionHandler : IRequestHandler<OverrideDecisionCommand, InspectionDto?>
{
    private readonly IDentDbContext _db;

    public OverrideDecisionHandler(IDentDbContext db) => _db = db;

    public async Task<InspectionDto?> Handle(OverrideDecisionCommand request, CancellationToken ct)
    {
        var query = _db.Inspections
            .Include(i => i.Damages)
            .Include(i => i.AdditionalImages)
            .Include(i => i.DecisionOverrides)
            .Include(i => i.ForensicResults)
            .AsQueryable();

        if (!request.IsAdmin && request.UserId.HasValue)
            query = query.Where(i => i.UserId == request.UserId.Value);

        var inspection = await query.FirstOrDefaultAsync(i => i.Id == request.InspectionId, ct);
        if (inspection is null) return null;

        var overrideEntry = new DecisionOverride
        {
            Id = Guid.NewGuid(),
            InspectionId = inspection.Id,
            OriginalOutcome = inspection.DecisionOutcome?.ToString() ?? "Unknown",
            NewOutcome = request.NewOutcome,
            Reason = request.Reason,
            OperatorName = request.OperatorName,
            CreatedAt = DateTime.UtcNow,
        };

        inspection.DecisionOutcome = Enum.TryParse<DecisionOutcome>(request.NewOutcome, true, out var outcome)
            ? outcome : DecisionOutcome.HumanReview;
        inspection.DecisionOverrides.Add(overrideEntry);

        await _db.SaveChangesAsync(ct);

        return InspectionMapper.MapToDto(inspection);
    }
}
