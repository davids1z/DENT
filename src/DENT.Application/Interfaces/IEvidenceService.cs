using DENT.Application.Models;

namespace DENT.Application.Interfaces;

public interface IEvidenceService
{
    string ComputeSha256(byte[] data);
    string ComputeSha256(string text);
    EvidenceCustodyEvent CreateCustodyEvent(string eventName, string? hash = null, string? details = null);
}
