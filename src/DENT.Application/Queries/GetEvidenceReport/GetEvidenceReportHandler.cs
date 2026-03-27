using System.Text.Json;
using DENT.Application.Interfaces;
using DENT.Domain.Entities;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetEvidenceReport;

public class GetEvidenceReportHandler : IRequestHandler<GetEvidenceReportQuery, byte[]?>
{
    private readonly IDentDbContext _db;
    private readonly IMlAnalysisService _mlService;

    public GetEvidenceReportHandler(IDentDbContext db, IMlAnalysisService mlService)
    {
        _db = db;
        _mlService = mlService;
    }

    public async Task<byte[]?> Handle(GetEvidenceReportQuery request, CancellationToken ct)
    {
        var inspection = await _db.Inspections
            .Include(i => i.Damages)
            .Include(i => i.ForensicResults)
            .AsNoTracking()
            .FirstOrDefaultAsync(i => i.Id == request.InspectionId, ct);

        if (inspection is null) return null;

        var payload = BuildPayload(inspection);
        return await _mlService.GenerateReportAsync(payload, ct);
    }

    internal static object BuildPayload(Inspection i)
    {
        var imageHashes = new List<object>();
        if (!string.IsNullOrEmpty(i.ImageHashesJson))
        {
            try
            {
                imageHashes = JsonSerializer.Deserialize<List<object>>(i.ImageHashesJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
            }
            catch { /* ignore */ }
        }

        var chainOfCustody = new List<object>();
        if (!string.IsNullOrEmpty(i.ChainOfCustodyJson))
        {
            try
            {
                chainOfCustody = JsonSerializer.Deserialize<List<object>>(i.ChainOfCustodyJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
            }
            catch { /* ignore */ }
        }

        var forensicModules = new List<object>();
        var primaryForensic = i.ForensicResults.OrderBy(f => f.SortOrder).FirstOrDefault();
        if (primaryForensic?.ModuleResultsJson is not null)
        {
            try
            {
                forensicModules = JsonSerializer.Deserialize<List<object>>(primaryForensic.ModuleResultsJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
            }
            catch { /* ignore */ }
        }

        object? agentDecision = null;
        if (!string.IsNullOrEmpty(i.AgentDecisionJson))
        {
            try
            {
                agentDecision = JsonSerializer.Deserialize<object>(i.AgentDecisionJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch { /* ignore */ }
        }

        return new
        {
            InspectionId = i.Id.ToString(),
            CreatedAt = i.CreatedAt.ToString("o"),
            CompletedAt = i.CompletedAt?.ToString("o"),
            VehicleMake = i.VehicleMake,
            VehicleModel = i.VehicleModel,
            VehicleYear = i.VehicleYear,
            VehicleColor = i.VehicleColor,
            TotalEstimatedCostMin = (double?)(i.TotalEstimatedCostMin),
            TotalEstimatedCostMax = (double?)(i.TotalEstimatedCostMax),
            GrossTotal = (double?)(i.GrossTotal),
            Currency = i.Currency,
            LaborTotal = (double?)(i.LaborTotal),
            PartsTotal = (double?)(i.PartsTotal),
            MaterialsTotal = (double?)(i.MaterialsTotal),
            IsDriveable = i.IsDriveable,
            UrgencyLevel = i.UrgencyLevel,
            StructuralIntegrity = i.StructuralIntegrity,
            Summary = i.Summary,
            DecisionOutcome = i.DecisionOutcome,
            DecisionReason = i.DecisionReason,
            FraudRiskScore = i.FraudRiskScore,
            FraudRiskLevel = i.FraudRiskLevel,
            ForensicModules = forensicModules,
            AgentDecision = agentDecision,
            Damages = i.Damages.Select(d => new
            {
                DamageType = d.DamageType.ToString(),
                CarPart = d.CarPart.ToString(),
                Severity = d.Severity.ToString(),
                d.Description,
                d.Confidence,
                d.RepairMethod,
                EstimatedCostMin = (double?)(d.EstimatedCostMin),
                EstimatedCostMax = (double?)(d.EstimatedCostMax),
                d.DamageCause,
                d.SafetyRating,
            }).ToList(),
            EvidenceHash = i.EvidenceHash,
            ImageHashes = imageHashes,
            ForensicResultHash = i.ForensicResultHash,
            AgentDecisionHash = i.AgentDecisionHash,
            ChainOfCustody = chainOfCustody,
            TimestampToken = i.TimestampToken,
            TimestampedAt = i.TimestampedAt?.ToString("o"),
            TimestampAuthority = i.TimestampAuthority,
        };
    }
}
