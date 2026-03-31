using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddGroupAnalysis : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "AnalysisMode",
                table: "Inspections",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "CrossImageFindingsJson",
                table: "Inspections",
                type: "text",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "AnalysisMode",
                table: "Inspections");

            migrationBuilder.DropColumn(
                name: "CrossImageFindingsJson",
                table: "Inspections");
        }
    }
}
