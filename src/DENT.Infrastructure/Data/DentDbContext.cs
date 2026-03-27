using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace DENT.Infrastructure.Data;

public class DentDbContext : DbContext, IDentDbContext
{
    public DentDbContext(DbContextOptions<DentDbContext> options) : base(options) { }

    public DbSet<Inspection> Inspections => Set<Inspection>();
    public DbSet<DamageDetection> DamageDetections => Set<DamageDetection>();
    public DbSet<InspectionImage> InspectionImages => Set<InspectionImage>();
    public DbSet<DecisionOverride> DecisionOverrides => Set<DecisionOverride>();
    public DbSet<ForensicResult> ForensicResults => Set<ForensicResult>();

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
            entity.Property(e => e.StructuralIntegrity).HasMaxLength(2000);

            // User-provided vehicle context
            entity.Property(e => e.UserProvidedMake).HasMaxLength(100);
            entity.Property(e => e.UserProvidedModel).HasMaxLength(100);

            // Capture metadata (Phase 6)
            entity.Property(e => e.CaptureDeviceInfo).HasMaxLength(2000);
            entity.Property(e => e.CaptureSource).HasMaxLength(20);

            // Structured cost totals
            entity.Property(e => e.LaborTotal).HasColumnType("decimal(10,2)");
            entity.Property(e => e.PartsTotal).HasColumnType("decimal(10,2)");
            entity.Property(e => e.MaterialsTotal).HasColumnType("decimal(10,2)");
            entity.Property(e => e.GrossTotal).HasColumnType("decimal(10,2)");

            // Decision engine
            entity.Property(e => e.DecisionOutcome).HasMaxLength(50);
            entity.Property(e => e.DecisionReason).HasMaxLength(2000);
            entity.Property(e => e.DecisionTraceJson).HasMaxLength(5000);

            // Agent decision (Phase 7)
            entity.Property(e => e.AgentDecisionJson).HasMaxLength(50000);
            entity.Property(e => e.AgentWeatherAssessment).HasMaxLength(2000);

            // Fraud detection
            entity.Property(e => e.FraudRiskLevel).HasMaxLength(50);

            // Evidence integrity (Phase 8)
            entity.Property(e => e.EvidenceHash).HasMaxLength(128);
            entity.Property(e => e.ImageHashesJson).HasMaxLength(10000);
            entity.Property(e => e.ForensicResultHash).HasMaxLength(128);
            entity.Property(e => e.AgentDecisionHash).HasMaxLength(128);
            entity.Property(e => e.ChainOfCustodyJson).HasMaxLength(50000);
            entity.Property(e => e.TimestampToken).HasMaxLength(10000);
            entity.Property(e => e.TimestampAuthority).HasMaxLength(500);

            entity.HasIndex(e => e.CreatedAt);
            entity.HasIndex(e => e.Status);
        });

        modelBuilder.Entity<ForensicResult>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.FileName).HasMaxLength(500);
            entity.Property(e => e.FileUrl).HasMaxLength(1000);
            entity.Property(e => e.OverallRiskLevel).HasMaxLength(50);
            entity.Property(e => e.ModuleResultsJson).HasMaxLength(50000);
            entity.Property(e => e.ElaHeatmapUrl).HasMaxLength(1000);
            entity.Property(e => e.FftSpectrumUrl).HasMaxLength(1000);
            entity.Property(e => e.SpectralHeatmapUrl).HasMaxLength(1000);
            entity.Property(e => e.PredictedSource).HasMaxLength(200);
            entity.Property(e => e.C2paStatus).HasMaxLength(50);
            entity.Property(e => e.C2paIssuer).HasMaxLength(500);
            entity.HasOne(e => e.Inspection)
                .WithMany(i => i.ForensicResults)
                .HasForeignKey(e => e.InspectionId)
                .OnDelete(DeleteBehavior.Cascade);
            entity.HasIndex(e => e.InspectionId);
        });

        modelBuilder.Entity<DamageDetection>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Description).IsRequired().HasMaxLength(2000);
            entity.Property(e => e.EstimatedCostMin).HasColumnType("decimal(10,2)");
            entity.Property(e => e.EstimatedCostMax).HasColumnType("decimal(10,2)");
            entity.Property(e => e.RepairMethod).HasMaxLength(500);
            entity.Property(e => e.PartsNeeded).HasMaxLength(1000);
            entity.Property(e => e.BoundingBox).HasMaxLength(200);
            entity.Property(e => e.DamageCause).HasMaxLength(500);
            entity.Property(e => e.SafetyRating).HasMaxLength(50);
            entity.Property(e => e.MaterialType).HasMaxLength(100);
            entity.Property(e => e.RepairOperations).HasMaxLength(2000);
            entity.Property(e => e.RepairCategory).HasMaxLength(50);
            entity.Property(e => e.RepairLineItemsJson).HasMaxLength(10000);
            entity.HasOne(e => e.Inspection)
                .WithMany(i => i.Damages)
                .HasForeignKey(e => e.InspectionId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<InspectionImage>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.ImageUrl).IsRequired().HasMaxLength(1000);
            entity.Property(e => e.OriginalFileName).IsRequired().HasMaxLength(500);
            entity.HasOne(e => e.Inspection)
                .WithMany(i => i.AdditionalImages)
                .HasForeignKey(e => e.InspectionId)
                .OnDelete(DeleteBehavior.Cascade);
            entity.HasIndex(e => e.InspectionId);
        });

        modelBuilder.Entity<DecisionOverride>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.OriginalOutcome).IsRequired().HasMaxLength(50);
            entity.Property(e => e.NewOutcome).IsRequired().HasMaxLength(50);
            entity.Property(e => e.Reason).IsRequired().HasMaxLength(2000);
            entity.Property(e => e.OperatorName).IsRequired().HasMaxLength(200);
            entity.HasOne(e => e.Inspection)
                .WithMany(i => i.DecisionOverrides)
                .HasForeignKey(e => e.InspectionId)
                .OnDelete(DeleteBehavior.Cascade);
            entity.HasIndex(e => e.InspectionId);
        });
    }
}
