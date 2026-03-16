using DENT.Application.Interfaces;
using DENT.Application.Queries.GetEvidenceReport;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace DENT.Application.Queries.GetEvidenceCertificate;

public class GetEvidenceCertificateHandler : IRequestHandler<GetEvidenceCertificateQuery, byte[]?>
{
    private readonly IDentDbContext _db;
    private readonly IMlAnalysisService _mlService;

    public GetEvidenceCertificateHandler(IDentDbContext db, IMlAnalysisService mlService)
    {
        _db = db;
        _mlService = mlService;
    }

    public async Task<byte[]?> Handle(GetEvidenceCertificateQuery request, CancellationToken ct)
    {
        var inspection = await _db.Inspections
            .Include(i => i.Damages)
            .Include(i => i.ForensicResult)
            .AsNoTracking()
            .FirstOrDefaultAsync(i => i.Id == request.InspectionId, ct);

        if (inspection is null) return null;

        var payload = GetEvidenceReportHandler.BuildPayload(inspection);
        return await _mlService.GenerateCertificateAsync(payload, ct);
    }
}
