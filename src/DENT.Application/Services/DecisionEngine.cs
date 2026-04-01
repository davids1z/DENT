using System.Text.Json;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;

namespace DENT.Application.Services;

public static class DecisionEngine
{
    public static (DecisionOutcome Outcome, string Reason, string TraceJson) Evaluate(Inspection inspection)
    {
        var traces = new List<DecisionTraceEntryDto>();
        var hasCriticalDamage = inspection.Damages.Any(d => d.Severity == DamageSeverity.Critical);
        var hasSevereFinding = inspection.Damages.Any(d => d.Severity == DamageSeverity.Severe);
        var hasSafetyCriticalDamage = inspection.Damages.Any(d => d.SafetyRating == SafetyRating.Critical);
        var findingCount = inspection.Damages.Count;

        var primaryForensic = inspection.ForensicResults.OrderBy(f => f.SortOrder).FirstOrDefault();
        var modules = ParseModuleScores(primaryForensic?.ModuleResultsJson);
        var aiGenScore = modules.GetValueOrDefault("ai_generation_detection", 0);
        var spectralScore = modules.GetValueOrDefault("spectral_forensics", 0);
        var cnnScore = modules.GetValueOrDefault("deep_modification_detection", 0);

        var hasCriticalFinding = hasCriticalDamage || aiGenScore >= 0.75;
        var fraudRiskScore = inspection.FraudRiskScore ?? 0;
        var hasSafetyCritical = hasSafetyCriticalDamage
            || (fraudRiskScore >= 0.60 && aiGenScore >= 0.60);

        var hasCriticalFraud = fraudRiskScore >= 0.85;
        var hasHighFraud = fraudRiskScore >= 0.40;
        var hasMediumFraud = fraudRiskScore >= 0.15;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Kritičan forenzički rizik",
            RuleDescription = "Forenzička analiza indicira visoku vjerojatnost manipulacije ili krivotvorenja",
            Triggered = hasCriticalFraud,
            ThresholdValue = ">= 75%",
            ActualValue = $"{fraudRiskScore * 100:F1}%",
            EvaluationOrder = 1
        });

        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Kritični nalaz AI analize",
            RuleDescription = "AI analiza detektirala kritične znakove krivotvorenja",
            Triggered = hasCriticalFinding,
            ThresholdValue = "Kritična oštećenja ili AI >= 75%",
            ActualValue = hasCriticalFinding ? "DA" : "NE",
            EvaluationOrder = 2
        });

        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Krivotvoreni sadržaj",
            RuleDescription = "AI verdikt označio sadržaj kao krivotvoreno",
            Triggered = hasSafetyCritical,
            ThresholdValue = "Kritična sigurnost ili rizik >= 60% + AI >= 60%",
            ActualValue = hasSafetyCritical ? "DA" : "NE",
            EvaluationOrder = 3
        });

        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Povišen forenzički rizik",
            RuleDescription = "Forenzička analiza pokazuje povišenu sumnju na manipulaciju",
            Triggered = hasHighFraud,
            ThresholdValue = ">= 40%",
            ActualValue = $"{fraudRiskScore * 100:F1}%",
            EvaluationOrder = 4
        });

        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Ozbiljni nalazi AI analize",
            RuleDescription = "AI analiza detektirala ozbiljne znakove manipulacije",
            Triggered = hasSevereFinding,
            ThresholdValue = "Barem 1 ozbiljan nalaz",
            ActualValue = hasSevereFinding ? "DA" : "NE",
            EvaluationOrder = 5
        });

        var findingsWithRisk = findingCount > 3 && hasMediumFraud;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Više nalaza uz povišeni rizik",
            RuleDescription = "Detektirano više od 3 sumnjiva nalaza uz forenzički rizik >= 15%",
            Triggered = findingsWithRisk,
            ThresholdValue = "> 3 nalaza + >= 15%",
            ActualValue = $"{findingCount} nalaza, rizik {fraudRiskScore * 100:F1}%",
            EvaluationOrder = 6
        });

        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Umjeren forenzički rizik",
            RuleDescription = "Forenzička analiza pokazuje umjerenu sumnju",
            Triggered = hasMediumFraud,
            ThresholdValue = ">= 15%",
            ActualValue = $"{fraudRiskScore * 100:F1}%",
            EvaluationOrder = 7
        });

        var aiGenTriggered = aiGenScore >= 0.60;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "AI detektor (neuronska mreža)",
            RuleDescription = "Swin Transformer ensemble detektirao AI-generirani sadržaj",
            Triggered = aiGenTriggered,
            ThresholdValue = ">= 60%",
            ActualValue = $"{aiGenScore * 100:F1}%",
            EvaluationOrder = 8
        });

        var crossValidated = aiGenScore >= 0.50 && spectralScore >= 0.40;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Spektralna cross-validacija",
            RuleDescription = "Dva nezavisna pristupa (NN + frekvencijska analiza) potvrđuju AI generiranje",
            Triggered = crossValidated,
            ThresholdValue = "AI >= 50% i Spektral >= 40%",
            ActualValue = $"AI: {aiGenScore * 100:F1}%, Spektral: {spectralScore * 100:F1}%",
            EvaluationOrder = 9
        });

        var isUpload = inspection.CaptureSource == CaptureSource.Upload;
        var uploadWithRisk = isUpload && hasMediumFraud;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Upload s povišenim rizikom",
            RuleDescription = "Datoteka uploadana (ne slikana kamerom) uz povišenu forenzičku sumnju",
            Triggered = uploadWithRisk,
            ThresholdValue = "Upload + >= 15%",
            ActualValue = $"Izvor: {(isUpload ? "Upload" : "Kamera")}, Rizik: {fraudRiskScore * 100:F1}%",
            EvaluationOrder = 10
        });

        DecisionOutcome outcome;
        string reason;

        if (hasCriticalFraud || hasCriticalFinding || hasSafetyCritical
            || aiGenTriggered || crossValidated)
        {
            outcome = DecisionOutcome.Escalate;
            var reasons = new List<string>();
            if (hasCriticalFraud) reasons.Add($"kritična sumnja na manipulaciju ({fraudRiskScore * 100:F1}%)");
            if (hasCriticalFinding) reasons.Add("kritični nalazi AI analize");
            if (hasSafetyCritical) reasons.Add("sadržaj označen kao krivotvoreno");
            if (aiGenTriggered) reasons.Add($"AI detektor: {aiGenScore * 100:F1}%");
            if (crossValidated) reasons.Add($"cross-validacija AI ({aiGenScore * 100:F1}%) + spektral ({spectralScore * 100:F1}%)");
            reason = $"Sumnja na krivotvorinu: {string.Join(", ", reasons)}";
        }
        else if (hasHighFraud || hasSevereFinding || findingsWithRisk
            || uploadWithRisk || cnnScore >= 0.50)
        {
            outcome = DecisionOutcome.HumanReview;
            var reasons = new List<string>();
            if (hasHighFraud) reasons.Add($"povišen forenzički rizik ({fraudRiskScore * 100:F1}%)");
            if (hasSevereFinding) reasons.Add("ozbiljni nalazi AI analize");
            if (findingCount > 3) reasons.Add($"{findingCount} sumnjivih nalaza");
            if (uploadWithRisk) reasons.Add("datoteka uploadana uz forenzičku sumnju");
            if (cnnScore >= 0.50) reasons.Add($"CNN detektor: {cnnScore * 100:F1}%");
            reason = $"Potreban pregled: {string.Join(", ", reasons)}";
        }
        else if (hasMediumFraud)
        {
            outcome = DecisionOutcome.HumanReview;
            reason = $"Potreban pregled: umjeren forenzički rizik ({fraudRiskScore * 100:F1}%)";
        }
        else
        {
            outcome = DecisionOutcome.AutoApprove;
            reason = $"Autentično: nizak forenzički rizik ({fraudRiskScore * 100:F1}%), {findingCount} nalaza";
        }

        var traceJson = JsonSerializer.Serialize(traces, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        });

        return (outcome, reason, traceJson);
    }

    private static Dictionary<string, double> ParseModuleScores(string? moduleResultsJson)
    {
        var scores = new Dictionary<string, double>();
        if (string.IsNullOrEmpty(moduleResultsJson)) return scores;

        try
        {
            using var doc = JsonDocument.Parse(moduleResultsJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Array) return scores;

            foreach (var element in doc.RootElement.EnumerateArray())
            {
                var name = element.TryGetProperty("moduleName", out var nameProp)
                    ? nameProp.GetString() ?? ""
                    : "";
                var score = element.TryGetProperty("riskScore", out var scoreProp)
                    ? scoreProp.GetDouble()
                    : 0.0;

                if (!string.IsNullOrEmpty(name))
                    scores[name] = score;
            }
        }
        catch
        {
        }

        return scores;
    }
}
