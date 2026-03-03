using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace DENT.Infrastructure.Data;

public class DentDbContext : DbContext, IDentDbContext
{
    public DentDbContext(DbContextOptions<DentDbContext> options) : base(options) { }

    public DbSet<Inspection> Inspections => Set<Inspection>();
    public DbSet<DamageDetection> DamageDetections => Set<DamageDetection>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<Inspection>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.ImageUrl).IsRequired().HasMaxLength(1000);
            entity.Property(e => e.OriginalFileName).IsRequired().HasMaxLength(500);
            entity.Property(e => e.Currency).HasMaxLength(10).HasDefaultValue("EUR");
            entity.Property(e => e.TotalEstimatedCostMin).HasColumnType("decimal(10,2)");
            entity.Property(e => e.TotalEstimatedCostMax).HasColumnType("decimal(10,2)");
            entity.Property(e => e.VehicleMake).HasMaxLength(100);
            entity.Property(e => e.VehicleModel).HasMaxLength(100);
            entity.Property(e => e.VehicleColor).HasMaxLength(50);
            entity.Property(e => e.UrgencyLevel).HasMaxLength(50);
            entity.HasIndex(e => e.CreatedAt);
            entity.HasIndex(e => e.Status);
        });

        modelBuilder.Entity<DamageDetection>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Description).IsRequired().HasMaxLength(2000);
            entity.Property(e => e.EstimatedCostMin).HasColumnType("decimal(10,2)");
            entity.Property(e => e.EstimatedCostMax).HasColumnType("decimal(10,2)");
            entity.Property(e => e.RepairMethod).HasMaxLength(500);
            entity.Property(e => e.PartsNeeded).HasMaxLength(1000);
            entity.HasOne(e => e.Inspection)
                .WithMany(i => i.Damages)
                .HasForeignKey(e => e.InspectionId)
                .OnDelete(DeleteBehavior.Cascade);
        });
    }
}
