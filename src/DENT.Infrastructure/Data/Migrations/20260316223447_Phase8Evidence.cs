using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class Phase8Evidence : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<double>(
                name: "AgentConfidence",
                table: "Inspections",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AgentDecisionHash",
                table: "Inspections",
                type: "character varying(128)",
                maxLength: 128,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "AgentDecisionJson",
                table: "Inspections",
                type: "character varying(50000)",
                maxLength: 50000,
                nullable: true);

            migrationBuilder.AddColumn<bool>(
                name: "AgentFallbackUsed",
                table: "Inspections",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<int>(
                name: "AgentProcessingTimeMs",
                table: "Inspections",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<bool>(
                name: "AgentStpEligible",
                table: "Inspections",
                type: "boolean",
                nullable: false,
                defaultValue: false);

            migrationBuilder.AddColumn<string>(
                name: "AgentWeatherAssessment",
                table: "Inspections",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "CaptureDeviceInfo",
                table: "Inspections",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<double>(
                name: "CaptureGpsAccuracy",
                table: "Inspections",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<double>(
                name: "CaptureLatitude",
                table: "Inspections",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<double>(
                name: "CaptureLongitude",
                table: "Inspections",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "CaptureSource",
                table: "Inspections",
                type: "character varying(20)",
                maxLength: 20,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ChainOfCustodyJson",
                table: "Inspections",
                type: "character varying(50000)",
                maxLength: 50000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "EvidenceHash",
                table: "Inspections",
                type: "character varying(128)",
                maxLength: 128,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ForensicResultHash",
                table: "Inspections",
                type: "character varying(128)",
                maxLength: 128,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "FraudRiskLevel",
                table: "Inspections",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<double>(
                name: "FraudRiskScore",
                table: "Inspections",
                type: "double precision",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ImageHashesJson",
                table: "Inspections",
                type: "character varying(10000)",
                maxLength: 10000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "TimestampAuthority",
                table: "Inspections",
                type: "character varying(500)",
                maxLength: 500,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "TimestampToken",
                table: "Inspections",
                type: "character varying(10000)",
                maxLength: 10000,
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "TimestampedAt",
                table: "Inspections",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.CreateTable(
                name: "ForensicResults",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    InspectionId = table.Column<Guid>(type: "uuid", nullable: false),
                    OverallRiskScore = table.Column<double>(type: "double precision", nullable: false),
                    OverallRiskLevel = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    ModuleResultsJson = table.Column<string>(type: "character varying(50000)", maxLength: 50000, nullable: false),
                    ElaHeatmapUrl = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true),
                    FftSpectrumUrl = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true),
                    TotalProcessingTimeMs = table.Column<int>(type: "integer", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_ForensicResults", x => x.Id);
                    table.ForeignKey(
                        name: "FK_ForensicResults_Inspections_InspectionId",
                        column: x => x.InspectionId,
                        principalTable: "Inspections",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_ForensicResults_InspectionId",
                table: "ForensicResults",
                column: "InspectionId",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "AgentConfidence",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentDecisionHash",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentDecisionJson",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentFallbackUsed",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentProcessingTimeMs",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentStpEligible",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "AgentWeatherAssessment",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CaptureDeviceInfo",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CaptureGpsAccuracy",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CaptureLatitude",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CaptureLongitude",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CaptureSource",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "ChainOfCustodyJson",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "EvidenceHash",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "ForensicResultHash",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "FraudRiskLevel",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "FraudRiskScore",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "ImageHashesJson",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "TimestampAuthority",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "TimestampToken",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "TimestampedAt",
                table: "Inspections");
        }
    }
}
