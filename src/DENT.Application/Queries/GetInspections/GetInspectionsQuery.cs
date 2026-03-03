using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Queries.GetInspections;

public record GetInspectionsQuery : IRequest<List<InspectionDto>>
{
    public int Page { get; init; } = 1;
    public int PageSize { get; init; } = 20;
    public string? Status { get; init; }
}
