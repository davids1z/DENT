using DENT.Application.Services;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Services;

public class EvidenceServiceTests
{
    private readonly EvidenceService _sut = new();

    [Fact]
    public void ComputeSha256_Bytes_ReturnsConsistentHash()
    {
        var data = "hello world"u8.ToArray();

        var hash1 = _sut.ComputeSha256(data);
        var hash2 = _sut.ComputeSha256(data);

        hash1.Should().Be(hash2);
        hash1.Should().HaveLength(64); // SHA256 hex = 64 chars
        hash1.Should().MatchRegex("^[0-9a-f]+$");
    }

    [Fact]
    public void ComputeSha256_String_ReturnsConsistentHash()
    {
        var hash1 = _sut.ComputeSha256("test data");
        var hash2 = _sut.ComputeSha256("test data");

        hash1.Should().Be(hash2);
    }

    [Fact]
    public void ComputeSha256_DifferentInputs_ReturnsDifferentHashes()
    {
        var hash1 = _sut.ComputeSha256("data1");
        var hash2 = _sut.ComputeSha256("data2");

        hash1.Should().NotBe(hash2);
    }

    [Fact]
    public void CreateCustodyEvent_PopulatesAllFields()
    {
        var before = DateTime.UtcNow;
        var evt = _sut.CreateCustodyEvent("test_event", "abc123", "some details");

        evt.Event.Should().Be("test_event");
        evt.Hash.Should().Be("abc123");
        evt.Details.Should().Be("some details");
        evt.Timestamp.Should().BeOnOrAfter(before);
    }

    [Fact]
    public void CreateCustodyEvent_NullOptionalFields_Works()
    {
        var evt = _sut.CreateCustodyEvent("event_only");

        evt.Event.Should().Be("event_only");
        evt.Hash.Should().BeNull();
        evt.Details.Should().BeNull();
    }
}
