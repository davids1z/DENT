using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class ProUpgrade : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "DecisionOutcome",
                table: "Inspections",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "DecisionReason",
                table: "Inspections",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "DecisionTraceJson",
                table: "Inspections",
                type: "character varying(5000)",
                maxLength: 5000,
                nullable: true);

            migrationBuilder.AddColumn<decimal>(
                name: "GrossTotal",
                table: "Inspections",
                type: "numeric(10,2)",
                nullable: true);

            migrationBuilder.AddColumn<decimal>(
                name: "LaborTotal",
                table: "Inspections",
                type: "numeric(10,2)",
                nullable: true);

            migrationBuilder.AddColumn<decimal>(
                name: "MaterialsTotal",
                table: "Inspections",
                type: "numeric(10,2)",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "Mileage",
                table: "Inspections",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<decimal>(
                name: "PartsTotal",
                table: "Inspections",
                type: "numeric(10,2)",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "UserProvidedMake",
                table: "Inspections",
                type: "character varying(100)",
                maxLength: 100,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "UserProvidedModel",
                table: "Inspections",
                type: "character varying(100)",
                maxLength: 100,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "UserProvidedYear",
                table: "Inspections",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "RepairLineItemsJson",
                table: "DamageDetections",
                type: "character varying(10000)",
                maxLength: 10000,
                nullable: true);

            migrationBuilder.CreateTable(
                name: "DecisionOverrides",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    InspectionId = table.Column<Guid>(type: "uuid", nullable: false),
                    OriginalOutcome = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    NewOutcome = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    Reason = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: false),
                    OperatorName = table.Column<string>(type: "character varying(200)", maxLength: 200, nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DecisionOverrides", x => x.Id);
                    table.ForeignKey(
                        name: "FK_DecisionOverrides_Inspections_InspectionId",
                        column: x => x.InspectionId,
                        principalTable: "Inspections",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "InspectionImages",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    InspectionId = table.Column<Guid>(type: "uuid", nullable: false),
                    ImageUrl = table.Column<string>(type: "character varying(1000)", maxLength: 1000, nullable: false),
                    OriginalFileName = table.Column<string>(type: "character varying(500)", maxLength: 500, nullable: false),
                    SortOrder = table.Column<int>(type: "integer", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_InspectionImages", x => x.Id);
                    table.ForeignKey(
                        name: "FK_InspectionImages_Inspections_InspectionId",
                        column: x => x.InspectionId,
                        principalTable: "Inspections",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_DecisionOverrides_InspectionId",
                table: "DecisionOverrides",
                column: "InspectionId");

            migrationBuilder.CreateIndex(
                name: "IX_InspectionImages_InspectionId",
                table: "InspectionImages",
                column: "InspectionId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "DecisionOverrides");

            migrationBuilder.DropTable(
                name: "InspectionImages");

            migrationBuilder.DropColumn(
                name: "DecisionOutcome",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "DecisionReason",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "DecisionTraceJson",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "GrossTotal",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "LaborTotal",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "MaterialsTotal",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "Mileage",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "PartsTotal",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "UserProvidedMake",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "UserProvidedModel",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "UserProvidedYear",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "RepairLineItemsJson",
                table: "DamageDetections");
        }
    }
}
