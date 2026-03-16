using MediatR;

namespace DENT.Application.Queries.GetEvidenceCertificate;

public record GetEvidenceCertificateQuery(Guid InspectionId) : IRequest<byte[]?>;
