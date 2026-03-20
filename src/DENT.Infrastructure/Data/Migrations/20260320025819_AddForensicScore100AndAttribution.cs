using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddForensicScore100AndAttribution : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "C2paIssuer",
                table: "ForensicResults",
                type: "character varying(500)",
                maxLength: 500,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "C2paStatus",
                table: "ForensicResults",
                type: "character varying(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "OverallRiskScore100",
                table: "ForensicResults",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.AddColumn<string>(
                name: "PredictedSource",
                table: "ForensicResults",
                type: "character varying(200)",
                maxLength: 200,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "SourceConfidence",
                table: "ForensicResults",
                type: "integer",
                nullable: false,
                defaultValue: 0);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "C2paIssuer",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "C2paStatus",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "OverallRiskScore100",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "PredictedSource",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "SourceConfidence",
                table: "ForensicResults");
        }
    }
}
