using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Inspections",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ImageUrl = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: false),
                    OriginalFileName = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: false),
                    ThumbnailUrl = table.Column<string>(type: "text", nullable: true),
                    Status = table.Column<int>(type: "integer", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    CompletedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    VehicleMake = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    VehicleModel = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: true),
                    VehicleYear = table.Column<int>(type: "integer", nullable: true),
                    VehicleColor = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    Summary = table.Column<string>(type: "text", nullable: true),
                    TotalEstimatedCostMin = table.Column<decimal>(type: "numeric(10,2)", nullable: true),
                    TotalEstimatedCostMax = table.Column<decimal>(type: "numeric(10,2)", nullable: true),
                    Currency = table.Column<string>(type: "character varying(10)", maxLength: 10, nullable: false, defaultValue: "EUR"),
                    IsDriveable = table.Column<bool>(type: "boolean", nullable: true),
                    UrgencyLevel = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    ErrorMessage = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Inspections", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "DamageDetections",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    InspectionId = table.Column<Guid>(type: "uuid", nullable: false),
                    DamageType = table.Column<int>(type: "integer", nullable: false),
                    CarPart = table.Column<int>(type: "integer", nullable: false),
                    Severity = table.Column<int>(type: "integer", nullable: false),
                    Description = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: false),
                    Confidence = table.Column<double>(type: "double precision", nullable: false),
                    RepairMethod = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: true),
                    EstimatedCostMin = table.Column<decimal>(type: "numeric(10,2)", nullable: true),
                    EstimatedCostMax = table.Column<decimal>(type: "numeric(10,2)", nullable: true),
                    LaborHours = table.Column<double>(type: "double precision", nullable: true),
                    PartsNeeded = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DamageDetections", x => x.Id);
                    table.ForeignKey(
                        name: "FK_DamageDetections_Inspections_InspectionId",
                        column: x => x.InspectionId,
                        principalTable: "Inspections",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_DamageDetections_InspectionId",
                table: "DamageDetections",
                column: "InspectionId");

            migrationBuilder.CreateIndex(
                name: "IX_Inspections_CreatedAt",
                table: "Inspections",
                column: "CreatedAt");

            migrationBuilder.CreateIndex(
                name: "IX_Inspections_Status",
                table: "Inspections",
                column: "Status");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "DamageDetections");

            migrationBuilder.DropTable(
                name: "Inspections");
        }
    }
}
