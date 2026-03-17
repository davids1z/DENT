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
        var hasCriticalFinding = inspection.Damages.Any(d => d.Severity == DamageSeverity.Critical);
        var hasSevereFinding = inspection.Damages.Any(d => d.Severity == DamageSeverity.Severe);
        var hasSafetyCritical = inspection.Damages.Any(d => d.SafetyRating == "Critical");
        var findingCount = inspection.Damages.Count;

        // Rule 1: Critical forensic risk
        var fraudRiskScore = inspection.FraudRiskScore ?? 0;
        var hasCriticalFraud = fraudRiskScore >= 0.75;
        var hasHighFraud = fraudRiskScore >= 0.50;
        var hasMediumFraud = fraudRiskScore >= 0.25;
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

        // Rule 6: Multiple findings
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Vise nalaza",
            RuleDescription = "Detektirano vise od 3 sumnjiva nalaza",
            Triggered = findingCount > 3,
            ThresholdValue = "3 nalaza",
            ActualValue = $"{findingCount} nalaza",
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

        // Determine outcome
        string outcome;
        string reason;

        if (hasCriticalFraud || hasCriticalFinding || hasSafetyCritical)
        {
            outcome = "Escalate";
            var reasons = new List<string>();
            if (hasCriticalFraud) reasons.Add($"kriticna sumnja na manipulaciju ({fraudRiskScore:P0})");
            if (hasCriticalFinding) reasons.Add("kriticni nalazi AI analize");
            if (hasSafetyCritical) reasons.Add("sadrzaj oznacen kao krivotvoreno");
            reason = $"Sumnja na krivotvorinu: {string.Join(", ", reasons)}";
        }
        else if (hasHighFraud || hasSevereFinding || findingCount > 3 || hasMediumFraud)
        {
            outcome = "HumanReview";
            var reasons = new List<string>();
            if (hasHighFraud) reasons.Add($"povisen forenzicki rizik ({fraudRiskScore:P0})");
            if (hasSevereFinding) reasons.Add("ozbiljni nalazi AI analize");
            if (findingCount > 3) reasons.Add($"{findingCount} sumnjivih nalaza");
            if (hasMediumFraud && !hasHighFraud) reasons.Add($"umjeren forenzicki rizik ({fraudRiskScore:P0})");
            reason = $"Potreban pregled: {string.Join(", ", reasons)}";
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
}
