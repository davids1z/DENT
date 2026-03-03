using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Commands.CreateInspection;

public record CreateInspectionCommand : IRequest<InspectionDto>
{
    public required Stream ImageStream { get; init; }
    public required string FileName { get; init; }
    public required string ContentType { get; init; }
}
