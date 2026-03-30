using DENT.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Interfaces;

public interface IDentDbContext
{
    DbSet<User> Users { get; }
    DbSet<Inspection> Inspections { get; }
    DbSet<DamageDetection> DamageDetections { get; }
    DbSet<InspectionImage> InspectionImages { get; }
    DbSet<DecisionOverride> DecisionOverrides { get; }
    DbSet<ForensicResult> ForensicResults { get; }
    DbSet<AuditEvent> AuditEvents { get; }
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
