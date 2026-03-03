using DENT.Application.Commands.CreateInspection;
using DENT.Application.Interfaces;
using DENT.Domain.Entities;
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
        var inspection = await _db.Inspections
            .Include(i => i.Damages)
            .Include(i => i.AdditionalImages)
            .Include(i => i.DecisionOverrides)
            .FirstOrDefaultAsync(i => i.Id == request.InspectionId, ct);

        if (inspection is null) return null;

        var overrideEntry = new DecisionOverride
        {
            Id = Guid.NewGuid(),
            InspectionId = inspection.Id,
            OriginalOutcome = inspection.DecisionOutcome ?? "Unknown",
            NewOutcome = request.NewOutcome,
            Reason = request.Reason,
            OperatorName = request.OperatorName,
            CreatedAt = DateTime.UtcNow,
        };

        inspection.DecisionOutcome = request.NewOutcome;
        inspection.DecisionOverrides.Add(overrideEntry);

        await _db.SaveChangesAsync(ct);

        return CreateInspectionHandler.MapToDto(inspection);
    }
}
