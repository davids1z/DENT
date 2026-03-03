using DENT.Shared.DTOs;
using MediatR;

namespace DENT.Application.Queries.GetDashboardStats;

public record GetDashboardStatsQuery : IRequest<DashboardStatsDto>;
