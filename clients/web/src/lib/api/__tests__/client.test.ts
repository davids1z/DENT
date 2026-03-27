import { describe, it, expect, vi, beforeEach } from "vitest";
import { getToken, setTokens, clearTokens, authHeaders } from "@/lib/api/client";

beforeEach(() => {
  localStorage.clear();
});

describe("getToken", () => {
  it("returns token from localStorage when it exists", () => {
    localStorage.setItem("dent_token", "test-jwt-token");
    expect(getToken()).toBe("test-jwt-token");
  });

  it("returns null when no token in localStorage", () => {
    expect(getToken()).toBeNull();
  });
});

describe("setTokens", () => {
  it("stores token and refresh token in localStorage", () => {
    setTokens("my-token", "my-refresh");

    expect(localStorage.getItem("dent_token")).toBe("my-token");
    expect(localStorage.getItem("dent_refresh_token")).toBe("my-refresh");
  });
});

describe("clearTokens", () => {
  it("removes token and refresh token from localStorage", () => {
    localStorage.setItem("dent_token", "some-token");
    localStorage.setItem("dent_refresh_token", "some-refresh");

    clearTokens();

    expect(localStorage.getItem("dent_token")).toBeNull();
    expect(localStorage.getItem("dent_refresh_token")).toBeNull();
  });
});

describe("setTokens/getToken/clearTokens flow", () => {
  it("full lifecycle: set, get, clear", () => {
    // Initially no token
    expect(getToken()).toBeNull();

    // Set tokens
    setTokens("access-123", "refresh-456");
    expect(getToken()).toBe("access-123");

    // Clear tokens
    clearTokens();
    expect(getToken()).toBeNull();
  });
});

describe("authHeaders", () => {
  it("returns Bearer header when token exists", () => {
    localStorage.setItem("dent_token", "jwt-token-xyz");

    const headers = authHeaders();
    expect(headers).toEqual({ Authorization: "Bearer jwt-token-xyz" });
  });

  it("returns empty object when no token", () => {
    const headers = authHeaders();
    expect(headers).toEqual({});
  });
});
