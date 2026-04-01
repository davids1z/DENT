using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace DENT.Infrastructure.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddPerceptualHashColumns : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "ClipEmbeddingB64",
                table: "ForensicResults",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "PerceptualHash",
                table: "ForensicResults",
                type: "character varying(16)",
                maxLength: 16,
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_ForensicResults_PerceptualHash",
                table: "ForensicResults",
                column: "PerceptualHash");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_ForensicResults_PerceptualHash",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "ClipEmbeddingB64",
                table: "ForensicResults");

            migrationBuilder.DropColumn(
                name: "PerceptualHash",
                table: "ForensicResults");
        }
    }
}
