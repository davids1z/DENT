using MediatR;

namespace DENT.Application.Queries.GetEvidenceReport;

public record GetEvidenceReportQuery(Guid InspectionId) : IRequest<byte[]?>;
