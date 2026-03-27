using System.Security.Cryptography;
using System.Text;
using DENT.Application.Interfaces;
using DENT.Application.Models;

namespace DENT.Application.Services;

public class EvidenceService : IEvidenceService
{
    public string ComputeSha256(byte[] data)
    {
        var hash = SHA256.HashData(data);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    public string ComputeSha256(string text)
    {
        return ComputeSha256(Encoding.UTF8.GetBytes(text));
    }

    public EvidenceCustodyEvent CreateCustodyEvent(string eventName, string? hash = null, string? details = null)
    {
        return new EvidenceCustodyEvent
        {
            Event = eventName,
            Timestamp = DateTime.UtcNow,
            Hash = hash,
            Details = details,
        };
    }
}
