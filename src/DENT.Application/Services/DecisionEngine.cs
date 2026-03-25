using System.Text.Json;
using DENT.Domain.Entities;
using DENT.Domain.Enums;
using DENT.Shared.DTOs;

namespace DENT.Application.Services;

public static class DecisionEngine
{
    public static (string Outcome, string Reason, string TraceJson) Evaluate(Inspection inspection)
    {
        var traces = new List<DecisionTraceEntryDto>();
        var hasCriticalDamage = inspection.Damages.Any(d => d.Severity == DamageSeverity.Critical);
        var hasSevereFinding = inspection.Damages.Any(d => d.Severity == DamageSeverity.Severe);
        var hasSafetyCriticalDamage = inspection.Damages.Any(d => d.SafetyRating == "Critical");
        var findingCount = inspection.Damages.Count;

        // Parse forensic module scores for fine-grained rules
        var modules = ParseModuleScores(inspection.ForensicResult?.ModuleResultsJson);
        var aiGenScore = modules.GetValueOrDefault("ai_generation_detection", 0);
        var spectralScore = modules.GetValueOrDefault("spectral_forensics", 0);
        var cnnScore = modules.GetValueOrDefault("deep_modification_detection", 0);

        // Forensic-based fallback: AI detector 75%+ is a critical finding
        var hasCriticalFinding = hasCriticalDamage || aiGenScore >= 0.75;
        // Forged content: from damage SafetyRating OR strong forensic + AI signal
        var fraudRiskScore = inspection.FraudRiskScore ?? 0;
        var hasSafetyCritical = hasSafetyCriticalDamage
            || (fraudRiskScore >= 0.60 && aiGenScore >= 0.60);

        // Rule 1: Critical forensic risk (fusion score) — aligned with Python 0.85
        var hasCriticalFraud = fraudRiskScore >= 0.85;
        var hasHighFraud = fraudRiskScore >= 0.40;
        var hasMediumFraud = fraudRiskScore >= 0.15;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Kritican forenzicki rizik",
            RuleDescription = "Forenzicka analiza indicira visoku vjerojatnost manipulacije ili krivotvorenja",
            Triggered = hasCriticalFraud,
            ThresholdValue = ">= 75% rizik",
            ActualValue = $"{fraudRiskScore:P0} rizik ({inspection.FraudRiskLevel ?? "N/A"})",
            EvaluationOrder = 1
        });

        // Rule 2: Critical finding from AI analysis
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Kriticni nalaz AI analize",
            RuleDescription = "AI analiza detektirala kriticne znakove krivotvorenja",
            Triggered = hasCriticalFinding,
            ThresholdValue = "0 kriticnih",
            ActualValue = hasCriticalFinding ? "DA" : "NE",
            EvaluationOrder = 2
        });

        // Rule 3: Safety critical (forged content)
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Krivotvoreni sadrzaj",
            RuleDescription = "AI verdikt oznacio sadrzaj kao krivotvoreno",
            Triggered = hasSafetyCritical,
            ThresholdValue = "0 krivotvorenih",
            ActualValue = hasSafetyCritical ? "DA" : "NE",
            EvaluationOrder = 3
        });

        // Rule 4: High forensic risk
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Povisen forenzicki rizik",
            RuleDescription = "Forenzicka analiza pokazuje povisenu sumnju na manipulaciju",
            Triggered = hasHighFraud,
            ThresholdValue = ">= 50% rizik",
            ActualValue = $"{fraudRiskScore:P0} rizik",
            EvaluationOrder = 4
        });

        // Rule 5: Severe findings from AI analysis
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Ozbiljni nalazi AI analize",
            RuleDescription = "AI analiza detektirala ozbiljne znakove manipulacije",
            Triggered = hasSevereFinding,
            ThresholdValue = "0 ozbiljnih",
            ActualValue = hasSevereFinding ? "DA" : "NE",
            EvaluationOrder = 5
        });

        // Rule 6: Multiple findings (only relevant when risk is elevated)
        var findingsWithRisk = findingCount > 3 && hasMediumFraud;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Vise nalaza uz poviseni rizik",
            RuleDescription = "Detektirano vise od 3 sumnjiva nalaza uz forenzicki rizik >= 15%",
            Triggered = findingsWithRisk,
            ThresholdValue = "3 nalaza + >= 15% rizik",
            ActualValue = $"{findingCount} nalaza, rizik {fraudRiskScore:P0}",
            EvaluationOrder = 6
        });

        // Rule 7: Medium forensic risk
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Umjeren forenzicki rizik",
            RuleDescription = "Forenzicka analiza pokazuje umjerenu sumnju",
            Triggered = hasMediumFraud,
            ThresholdValue = ">= 25% rizik",
            ActualValue = $"{fraudRiskScore:P0} rizik",
            EvaluationOrder = 7
        });

        // Rule 8: AI generation detector strong signal
        var aiGenTriggered = aiGenScore >= 0.60;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "AI detektor (neuronska mreza)",
            RuleDescription = "Swin Transformer ensemble detektirao AI-generirani sadrzaj",
            Triggered = aiGenTriggered,
            ThresholdValue = ">= 60% rizik",
            ActualValue = $"{aiGenScore:P0}",
            EvaluationOrder = 8
        });

        // Rule 9: Spectral + AI cross-validation
        var crossValidated = aiGenScore >= 0.50 && spectralScore >= 0.40;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Spektralna cross-validacija",
            RuleDescription = "Dva nezavisna pristupa (NN + frekvencijska analiza) potvrduju AI generiranje",
            Triggered = crossValidated,
            ThresholdValue = "AI >= 50% I Spektral >= 40%",
            ActualValue = $"AI: {aiGenScore:P0}, Spektral: {spectralScore:P0}",
            EvaluationOrder = 9
        });

        // Rule 10: Capture source is upload with elevated risk
        var isUpload = inspection.CaptureSource == "upload";
        var uploadWithRisk = isUpload && hasMediumFraud;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Upload s povisenim rizikom",
            RuleDescription = "Slika uploadana (ne slikana kamerom) uz povisenu forenzicku sumnju",
            Triggered = uploadWithRisk,
            ThresholdValue = "Upload + >= 25% rizik",
            ActualValue = $"Izvor: {inspection.CaptureSource ?? "N/A"}, Rizik: {fraudRiskScore:P0}",
            EvaluationOrder = 10
        });

        // Determine outcome — DETERMINISTIC from fusion scores + module signals
        string outcome;
        string reason;

        if (hasCriticalFraud || hasCriticalFinding || hasSafetyCritical
            || aiGenTriggered || crossValidated)
        {
            outcome = "Escalate";
            var reasons = new List<string>();
            if (hasCriticalFraud) reasons.Add($"kriticna sumnja na manipulaciju ({fraudRiskScore:P0})");
            if (hasCriticalFinding) reasons.Add("kriticni nalazi AI analize");
            if (hasSafetyCritical) reasons.Add("sadrzaj oznacen kao krivotvoreno");
            if (aiGenTriggered) reasons.Add($"AI detektor: {aiGenScore:P0}");
            if (crossValidated) reasons.Add($"cross-validacija AI ({aiGenScore:P0}) + spektral ({spectralScore:P0})");
            reason = $"Sumnja na krivotvorinu: {string.Join(", ", reasons)}";
        }
        // findingCount only triggers review when risk is elevated (>= 15%).
        // Low-risk images with many findings = false positives from noisy modules.
        else if (hasHighFraud || hasSevereFinding || findingsWithRisk
            || uploadWithRisk || cnnScore >= 0.50)
        {
            outcome = "HumanReview";
            var reasons = new List<string>();
            if (hasHighFraud) reasons.Add($"povisen forenzicki rizik ({fraudRiskScore:P0})");
            if (hasSevereFinding) reasons.Add("ozbiljni nalazi AI analize");
            if (findingCount > 3) reasons.Add($"{findingCount} sumnjivih nalaza");
            if (uploadWithRisk) reasons.Add("slika uploadana uz forenzicku sumnju");
            if (cnnScore >= 0.50) reasons.Add($"CNN detektor: {cnnScore:P0}");
            reason = $"Potreban pregled: {string.Join(", ", reasons)}";
        }
        else if (hasMediumFraud)
        {
            outcome = "HumanReview";
            reason = $"Potreban pregled: umjeren forenzicki rizik ({fraudRiskScore:P0})";
        }
        else
        {
            outcome = "AutoApprove";
            reason = $"Autenticno: nizak forenzicki rizik ({fraudRiskScore:P0}), {findingCount} nalaza";
        }

        var traceJson = JsonSerializer.Serialize(traces, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        });

        return (outcome, reason, traceJson);
    }

    /// <summary>
    /// Parse individual module risk scores from the forensic results JSON.
    /// Returns a dictionary of module_name → risk_score.
    /// </summary>
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
            // If JSON parsing fails, return empty — fusion score still works
        }

        return scores;
    }
}
