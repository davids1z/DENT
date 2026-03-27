using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Commands.OverrideDecision;

public record OverrideDecisionCommand : IRequest<InspectionDto?>
{
    public Guid InspectionId { get; init; }
    public Guid? UserId { get; init; }
    public bool IsAdmin { get; init; }
    public required string NewOutcome { get; init; }
    public required string Reason { get; init; }
    public required string OperatorName { get; init; }
}
