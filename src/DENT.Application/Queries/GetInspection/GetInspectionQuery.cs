using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Queries.GetInspection;

public record GetInspectionQuery(Guid Id) : IRequest<InspectionDto?>
{
    public Guid? UserId { get; init; }
}
