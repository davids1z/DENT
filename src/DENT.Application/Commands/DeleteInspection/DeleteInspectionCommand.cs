using MediatR;

namespace DENT.Application.Commands.DeleteInspection;

public record DeleteInspectionCommand(Guid Id) : IRequest<bool>
{
    public Guid? UserId { get; init; }
}
