using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class PerFileForensicResults : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_ForensicResults_InspectionId",
                table: "ForensicResults");

            migrationBuilder.AddColumn<string>(
                name: "FileName",
                table: "ForensicResults",
                type: "character varying(500)",
                maxLength: 500,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "FileUrl",
                table: "ForensicResults",
                type: "character varying(1000)",
                maxLength: 1000,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "SortOrder",
                table: "ForensicResults",
                type: "integer",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.CreateIndex(
                name: "IX_ForensicResults_InspectionId",
                table: "ForensicResults",
                column: "InspectionId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_ForensicResults_InspectionId",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "FileName",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "FileUrl",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "SortOrder",
                table: "ForensicResults");

            migrationBuilder.CreateIndex(
                name: "IX_ForensicResults_InspectionId",
                table: "ForensicResults",
                column: "InspectionId",
                unique: true);
        }
    }
}
