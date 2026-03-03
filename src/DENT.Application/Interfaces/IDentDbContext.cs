using DENT.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Interfaces;

public interface IDentDbContext
{
    DbSet<Inspection> Inspections { get; }
    DbSet<DamageDetection> DamageDetections { get; }
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
