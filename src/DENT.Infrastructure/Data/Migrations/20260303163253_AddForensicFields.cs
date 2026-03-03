using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddForensicFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "StructuralIntegrity",
                table: "Inspections",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "BoundingBox",
                table: "DamageDetections",
                type: "character varying(200)",
                maxLength: 200,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "DamageCause",
                table: "DamageDetections",
                type: "character varying(500)",
                maxLength: 500,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "MaterialType",
                table: "DamageDetections",
                type: "character varying(100)",
                maxLength: 100,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "RepairCategory",
                table: "DamageDetections",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "RepairOperations",
                table: "DamageDetections",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SafetyRating",
                table: "DamageDetections",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "StructuralIntegrity",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "BoundingBox",
                table: "DamageDetections");

            migrationBuilder.DropColumn(
                name: "DamageCause",
                table: "DamageDetections");

            migrationBuilder.DropColumn(
                name: "MaterialType",
                table: "DamageDetections");

            migrationBuilder.DropColumn(
                name: "RepairCategory",
                table: "DamageDetections");

            migrationBuilder.DropColumn(
                name: "RepairOperations",
                table: "DamageDetections");

            migrationBuilder.DropColumn(
                name: "SafetyRating",
                table: "DamageDetections");
        }
    }
}
