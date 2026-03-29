using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Queries.GetAdminStats;

public record GetAdminStatsQuery : IRequest<AdminStatsDto>;
