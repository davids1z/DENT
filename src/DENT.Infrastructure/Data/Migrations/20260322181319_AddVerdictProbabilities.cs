using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddVerdictProbabilities : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "VerdictProbabilitiesJson",
                table: "ForensicResults",
                type: "text",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "VerdictProbabilitiesJson",
                table: "ForensicResults");
        }
    }
}
