import { describe, it, expect } from "vitest";

// Inline the pure utilities under test (they're not exported from the component)
function safeHostname(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function safeFavicon(url: string): string {
  try { return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=16`; } catch { return ""; }
}

function formatCost(usd: number): string {
  if (usd < 0.00001) return "";
  if (usd < 0.0001) return "<0.01¢";
  if (usd < 0.01) return `${(usd * 100).toFixed(2)}¢`;
  return `$${usd.toFixed(4)}`;
}

// ── safeHostname ─────────────────────────────────────────────────────────────

describe("safeHostname", () => {
  it("extracts hostname from a valid URL", () => {
    expect(safeHostname("https://example.com/path")).toBe("example.com");
  });

  it("strips www. prefix", () => {
    expect(safeHostname("https://www.google.com/search")).toBe("google.com");
  });

  it("handles subdomain without www", () => {
    expect(safeHostname("https://docs.anthropic.com/page")).toBe("docs.anthropic.com");
  });

  it("returns original string for invalid URL", () => {
    expect(safeHostname("not a url")).toBe("not a url");
  });

  it("returns empty string for empty input", () => {
    expect(safeHostname("")).toBe("");
  });
});

// ── safeFavicon ───────────────────────────────────────────────────────────────

describe("safeFavicon", () => {
  it("returns Google favicon URL for valid URL", () => {
    const result = safeFavicon("https://example.com/page");
    expect(result).toContain("google.com/s2/favicons");
    expect(result).toContain("example.com");
    expect(result).toContain("sz=16");
  });

  it("returns empty string for invalid URL", () => {
    expect(safeFavicon("not a url")).toBe("");
  });

  it("returns empty string for empty input", () => {
    expect(safeFavicon("")).toBe("");
  });

  it("uses hostname not full URL in favicon request", () => {
    const result = safeFavicon("https://www.github.com/user/repo");
    expect(result).toContain("www.github.com");
    expect(result).not.toContain("/user/repo");
  });
});

// ── formatCost ────────────────────────────────────────────────────────────────

describe("formatCost", () => {
  it("returns empty string for negligible cost", () => {
    expect(formatCost(0)).toBe("");
    expect(formatCost(0.000001)).toBe("");
  });

  it("returns <0.01¢ for very small cost", () => {
    expect(formatCost(0.00005)).toBe("<0.01¢");
  });

  it("returns cents for sub-dollar cost", () => {
    expect(formatCost(0.005)).toBe("0.50¢");
  });

  it("returns dollar format for larger costs", () => {
    expect(formatCost(0.05)).toBe("$0.0500");
  });
});
