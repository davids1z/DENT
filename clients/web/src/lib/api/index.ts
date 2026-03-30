// Re-export everything for backward compatibility with `import { ... } from "@/lib/api"`
export * from "./types";
export * from "./client";
export * from "./auth";
export * from "./inspections";
export * from "./formatters";
export * from "./audit";

// Legacy aliases for renamed functions
export { uploadInspection as uploadInspectionWithMetadata } from "./inspections";
export { uploadInspectionsSeparate as uploadInspections } from "./inspections";
