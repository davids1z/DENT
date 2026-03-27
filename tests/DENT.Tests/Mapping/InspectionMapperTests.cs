using DENT.Application.Mapping;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Mapping;

public class InspectionMapperTests
{
    private static Inspection CreateTestInspection() => new()
    {
        Id = Guid.NewGuid(),
        ImageUrl = "https://example.com/img.jpg",
        OriginalFileName = "test.jpg",
        Status = InspectionStatus.Completed,
        CreatedAt = DateTime.UtcNow,
        CaptureSource = CaptureSource.Camera,
        UrgencyLevel = UrgencyLevel.High,
        DecisionOutcome = DecisionOutcome.HumanReview,
        FraudRiskLevel = FraudRiskLevel.Medium,
        FraudRiskScore = 0.45,
        Damages = [],
        AdditionalImages = [],
        DecisionOverrides = [],
        ForensicResults = [],
    };

    [Fact]
    public void MapToDto_MapsScalarFields()
    {
        var inspection = CreateTestInspection();

        var dto = InspectionMapper.MapToDto(inspection);

        dto.Id.Should().Be(inspection.Id);
        dto.ImageUrl.Should().Be(inspection.ImageUrl);
        dto.Status.Should().Be("Completed");
        dto.CaptureSource.Should().Be("Camera");
        dto.UrgencyLevel.Should().Be("High");
        dto.DecisionOutcome.Should().Be("HumanReview");
        dto.FraudRiskLevel.Should().Be("Medium");
        dto.FraudRiskScore.Should().Be(0.45);
    }

    [Fact]
    public void MapToDto_NullEnums_MappedAsNull()
    {
        var inspection = CreateTestInspection();
        inspection.DecisionOutcome = null;
        inspection.UrgencyLevel = null;
        inspection.FraudRiskLevel = null;
        inspection.CaptureSource = null;

        var dto = InspectionMapper.MapToDto(inspection);

        dto.DecisionOutcome.Should().BeNull();
        dto.UrgencyLevel.Should().BeNull();
        dto.FraudRiskLevel.Should().BeNull();
        dto.CaptureSource.Should().BeNull();
    }

    [Fact]
    public void MapToDto_MapsDamages_WithEnums()
    {
        var inspection = CreateTestInspection();
        inspection.Damages.Add(new DamageDetection
        {
            Id = Guid.NewGuid(),
            InspectionId = inspection.Id,
            DamageType = DamageType.Scratch,
            CarPart = CarPart.FrontBumper,
            Severity = DamageSeverity.Minor,
            SafetyRating = SafetyRating.Safe,
            RepairCategory = RepairCategory.Repair,
            Description = "Small scratch",
        });

        var dto = InspectionMapper.MapToDto(inspection);

        dto.Damages.Should().HaveCount(1);
        dto.Damages[0].DamageType.Should().Be("Scratch");
        dto.Damages[0].SafetyRating.Should().Be("Safe");
        dto.Damages[0].RepairCategory.Should().Be("Repair");
    }

    [Fact]
    public void MapToDto_MapsForensicResults_Ordered()
    {
        var inspection = CreateTestInspection();
        inspection.ForensicResults.Add(new ForensicResult
        {
            Id = Guid.NewGuid(),
            InspectionId = inspection.Id,
            SortOrder = 1,
            OverallRiskScore = 0.3,
            OverallRiskLevel = "Low",
            ModuleResultsJson = "[]",
        });
        inspection.ForensicResults.Add(new ForensicResult
        {
            Id = Guid.NewGuid(),
            InspectionId = inspection.Id,
            SortOrder = 0,
            OverallRiskScore = 0.8,
            OverallRiskLevel = "High",
            ModuleResultsJson = "[]",
        });

        var dto = InspectionMapper.MapToDto(inspection);

        dto.ForensicResult.Should().NotBeNull();
        dto.ForensicResult!.SortOrder.Should().Be(0);
        dto.ForensicResult.OverallRiskScore.Should().Be(0.8);
        dto.FileForensicResults.Should().HaveCount(2);
        dto.FileForensicResults[0].SortOrder.Should().Be(0);
    }

    [Fact]
    public void ParseDecisionTraces_ValidJson_ReturnsTraces()
    {
        var json = """[{"ruleName":"Test","triggered":true,"evaluationOrder":1}]""";

        var traces = InspectionMapper.ParseDecisionTraces(json);

        traces.Should().HaveCount(1);
        traces[0].RuleName.Should().Be("Test");
    }

    [Fact]
    public void ParseDecisionTraces_NullJson_ReturnsEmpty()
    {
        var traces = InspectionMapper.ParseDecisionTraces(null);
        traces.Should().BeEmpty();
    }

    [Fact]
    public void ParseDecisionTraces_MalformedJson_ReturnsEmpty()
    {
        var traces = InspectionMapper.ParseDecisionTraces("not json");
        traces.Should().BeEmpty();
    }

    [Fact]
    public void ParseForensicModules_ValidJson_ReturnsModules()
    {
        var json = """[{"moduleName":"clip_ai_detection","riskScore":0.75,"riskLevel":"High"}]""";

        var modules = InspectionMapper.ParseForensicModules(json);

        modules.Should().HaveCount(1);
        modules[0].ModuleName.Should().Be("clip_ai_detection");
    }
}
