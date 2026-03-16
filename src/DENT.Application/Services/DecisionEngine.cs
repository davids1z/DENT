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
        var totalCostMax = inspection.TotalEstimatedCostMax ?? inspection.GrossTotal ?? 0;
        var hasCriticalDamage = inspection.Damages.Any(d => d.Severity == DamageSeverity.Critical);
        var hasSevereDamage = inspection.Damages.Any(d => d.Severity == DamageSeverity.Severe);
        var hasSafetyCritical = inspection.Damages.Any(d => d.SafetyRating == "Critical");
        var hasStructuralIssue = !string.IsNullOrEmpty(inspection.StructuralIntegrity)
            && inspection.StructuralIntegrity.Contains("pomicanje", StringComparison.OrdinalIgnoreCase);
        var damageCount = inspection.Damages.Count;

        // Rule 1: Cost threshold - Escalate
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Visok trosak",
            RuleDescription = "Ukupni trosak prelazi 3.000 EUR",
            Triggered = totalCostMax > 3000,
            ThresholdValue = "3.000 EUR",
            ActualValue = $"{totalCostMax:N0} EUR",
            EvaluationOrder = 1
        });

        // Rule 2: Critical damage severity
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Kriticna ozbiljnost",
            RuleDescription = "Barem jedno ostecenje kriticne ozbiljnosti",
            Triggered = hasCriticalDamage,
            ThresholdValue = "0 kriticnih",
            ActualValue = hasCriticalDamage ? "DA" : "NE",
            EvaluationOrder = 2
        });

        // Rule 3: Safety critical (windshield in driver FOV, etc.)
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Sigurnosno kriticno",
            RuleDescription = "Ostecenje s kriticnom sigurnosnom ocjenom",
            Triggered = hasSafetyCritical,
            ThresholdValue = "0 kriticnih",
            ActualValue = hasSafetyCritical ? "DA" : "NE",
            EvaluationOrder = 3
        });

        // Rule 4: Structural integrity
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Strukturalni integritet",
            RuleDescription = "Moguce strukturno pomicanje ili ostecenje sasije",
            Triggered = hasStructuralIssue,
            ThresholdValue = "Intaktna sasija",
            ActualValue = hasStructuralIssue ? "KOMPROMITIRAN" : "OK",
            EvaluationOrder = 4
        });

        // Rule 5: Severe damage
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Ozbiljna ostecenja",
            RuleDescription = "Barem jedno ostecenje ozbiljne razine",
            Triggered = hasSevereDamage,
            ThresholdValue = "0 ozbiljnih",
            ActualValue = hasSevereDamage ? "DA" : "NE",
            EvaluationOrder = 5
        });

        // Rule 6: Medium cost threshold
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Srednji trosak",
            RuleDescription = "Ukupni trosak izmedu 500 i 3.000 EUR",
            Triggered = totalCostMax >= 500 && totalCostMax <= 3000,
            ThresholdValue = "500-3.000 EUR",
            ActualValue = $"{totalCostMax:N0} EUR",
            EvaluationOrder = 6
        });

        // Rule 7: Many damages
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Vise ostecenja",
            RuleDescription = "Vise od 5 detektiranih ostecenja",
            Triggered = damageCount > 5,
            ThresholdValue = "5 ostecenja",
            ActualValue = $"{damageCount} ostecenja",
            EvaluationOrder = 7
        });

        // Rule 8: Fraud risk
        var fraudRiskScore = inspection.FraudRiskScore ?? 0;
        var hasCriticalFraud = fraudRiskScore >= 0.75;
        var hasFraudRisk = fraudRiskScore >= 0.50;
        traces.Add(new DecisionTraceEntryDto
        {
            RuleName = "Rizik prijevare",
            RuleDescription = "Forenzicka analiza indicira moguce manipulacije slika ili dokumenata",
            Triggered = hasFraudRisk,
            ThresholdValue = "< 50% rizik",
            ActualValue = $"{fraudRiskScore:P0} rizik ({inspection.FraudRiskLevel ?? "N/A"})",
            EvaluationOrder = 8
        });

        // Determine outcome
        string outcome;
        string reason;

        if (totalCostMax > 3000 || hasCriticalDamage || hasSafetyCritical || hasStructuralIssue || hasCriticalFraud)
        {
            outcome = "Escalate";
            var reasons = new List<string>();
            if (totalCostMax > 3000) reasons.Add($"visok trosak ({totalCostMax:N0} EUR)");
            if (hasCriticalDamage) reasons.Add("kriticna ostecenja");
            if (hasSafetyCritical) reasons.Add("sigurnosno kriticno");
            if (hasStructuralIssue) reasons.Add("strukturno ostecenje");
            if (hasCriticalFraud) reasons.Add("kriticna sumnja na manipulaciju");
            reason = $"Eskalirano: {string.Join(", ", reasons)}";
        }
        else if (totalCostMax >= 500 || hasSevereDamage || damageCount > 5 || hasFraudRisk)
        {
            outcome = "HumanReview";
            var reasons = new List<string>();
            if (totalCostMax >= 500) reasons.Add($"srednji trosak ({totalCostMax:N0} EUR)");
            if (hasSevereDamage) reasons.Add("ozbiljna ostecenja");
            if (damageCount > 5) reasons.Add($"{damageCount} ostecenja");
            if (hasFraudRisk) reasons.Add("povisen rizik prijevare");
            reason = $"Potreban pregled: {string.Join(", ", reasons)}";
        }
        else
        {
            outcome = "AutoApprove";
            reason = $"Automatski odobreno: nizak trosak ({totalCostMax:N0} EUR), {damageCount} manjih ostecenja";
        }

        var traceJson = JsonSerializer.Serialize(traces, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        });

        return (outcome, reason, traceJson);
    }
}
