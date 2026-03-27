using DENT.Application.Services;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using FluentAssertions;
using Xunit;

namespace DENT.Tests.Services;

public class DecisionEngineTests
{
    private static Inspection CreateInspection(
        double fraudRiskScore = 0,
        FraudRiskLevel? fraudRiskLevel = null,
        CaptureSource? captureSource = null,
        string? moduleResultsJson = null)
    {
        var inspection = new Inspection
        {
            Id = Guid.NewGuid(),
            FraudRiskScore = fraudRiskScore,
            FraudRiskLevel = fraudRiskLevel ?? FraudRiskLevel.Low,
            CaptureSource = captureSource ?? CaptureSource.Upload,
            Damages = [],
            ForensicResults = [],
            DecisionOverrides = [],
            AdditionalImages = [],
        };

        if (moduleResultsJson != null)
        {
            inspection.ForensicResults.Add(new ForensicResult
            {
                Id = Guid.NewGuid(),
                InspectionId = inspection.Id,
                SortOrder = 0,
                ModuleResultsJson = moduleResultsJson,
                OverallRiskLevel = "Low",
            });
        }

        return inspection;
    }

    [Fact]
    public void Evaluate_CriticalFraudRisk_Returns_Escalate()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.90, fraudRiskLevel: FraudRiskLevel.Critical);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.Escalate);
        reason.Should().Contain("kriticna sumnja na manipulaciju");
    }

    [Fact]
    public void Evaluate_HighAiGenScore_Returns_Escalate()
    {
        var json = """[{"moduleName":"ai_generation_detection","riskScore":0.80}]""";
        var inspection = CreateInspection(fraudRiskScore: 0.50, moduleResultsJson: json);

        var (outcome, _, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.Escalate);
    }

    [Fact]
    public void Evaluate_CrossValidated_AI_Spectral_Returns_Escalate()
    {
        var json = """[{"moduleName":"ai_generation_detection","riskScore":0.55},{"moduleName":"spectral_forensics","riskScore":0.45}]""";
        var inspection = CreateInspection(fraudRiskScore: 0.30, moduleResultsJson: json);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.Escalate);
        reason.Should().Contain("cross-validacija");
    }

    [Fact]
    public void Evaluate_HighFraudRisk_Returns_HumanReview()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.50, fraudRiskLevel: FraudRiskLevel.High);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.HumanReview);
        reason.Should().Contain("povisen forenzicki rizik");
    }

    [Fact]
    public void Evaluate_MediumFraud_Returns_HumanReview()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.20, fraudRiskLevel: FraudRiskLevel.Medium);

        var (outcome, _, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.HumanReview);
    }

    [Fact]
    public void Evaluate_LowRisk_NoFindings_Returns_AutoApprove()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.05, fraudRiskLevel: FraudRiskLevel.Low);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.AutoApprove);
        reason.Should().Contain("Autenticno");
    }

    [Fact]
    public void Evaluate_ManyFindings_LowRisk_Returns_AutoApprove()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.05);
        for (int i = 0; i < 5; i++)
            inspection.Damages.Add(new DamageDetection
            {
                InspectionId = inspection.Id,
                DamageType = DamageType.Scratch,
                CarPart = CarPart.FrontBumper,
                Severity = DamageSeverity.Minor,
                Description = "test",
            });

        var (outcome, _, _) = DecisionEngine.Evaluate(inspection);

        // Many findings but low risk → AutoApprove (not triggered by count alone)
        outcome.Should().Be(DecisionOutcome.AutoApprove);
    }

    [Fact]
    public void Evaluate_Upload_WithMediumRisk_Returns_HumanReview()
    {
        var inspection = CreateInspection(
            fraudRiskScore: 0.20,
            captureSource: CaptureSource.Upload);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.HumanReview);
        reason.Should().Contain("uploadana");
    }

    [Fact]
    public void Evaluate_SevereFinding_Returns_HumanReview()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.10);
        inspection.Damages.Add(new DamageDetection
        {
            InspectionId = inspection.Id,
            DamageType = DamageType.BodyDeformation,
            CarPart = CarPart.Hood,
            Severity = DamageSeverity.Severe,
            Description = "test",
        });

        var (outcome, _, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.HumanReview);
    }

    [Fact]
    public void Evaluate_SafetyCriticalDamage_Returns_Escalate()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.10);
        inspection.Damages.Add(new DamageDetection
        {
            InspectionId = inspection.Id,
            DamageType = DamageType.Crack,
            CarPart = CarPart.Windshield,
            Severity = DamageSeverity.Critical,
            SafetyRating = SafetyRating.Critical,
            Description = "test",
        });

        var (outcome, _, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.Escalate);
    }

    [Fact]
    public void Evaluate_NullForensicResults_Returns_AutoApprove()
    {
        var inspection = CreateInspection(fraudRiskScore: 0.0);

        var (outcome, _, traceJson) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.AutoApprove);
        traceJson.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public void Evaluate_CnnSignal_Returns_HumanReview()
    {
        var json = """[{"moduleName":"deep_modification_detection","riskScore":0.55}]""";
        var inspection = CreateInspection(fraudRiskScore: 0.10, moduleResultsJson: json);

        var (outcome, reason, _) = DecisionEngine.Evaluate(inspection);

        outcome.Should().Be(DecisionOutcome.HumanReview);
        reason.Should().Contain("CNN detektor");
    }
}
