import { describe, it, expect } from "vitest";
import {
  formatNumber,
  formatPercent,
  formatDateTime,
  formatShortDate,
  formatMoney,
  trendSign,
} from "@/utils/format";

describe("formatNumber", () => {
  it("formats integers with zh-CN locale", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });

  it("returns '--' for null", () => {
    expect(formatNumber(null)).toBe("--");
  });

  it("returns '--' for undefined", () => {
    expect(formatNumber(undefined)).toBe("--");
  });

  it("formats zero", () => {
    expect(formatNumber(0)).toBe("0");
  });
});

describe("formatPercent", () => {
  it("returns percentage string", () => {
    expect(formatPercent(85)).toBe("85%");
  });

  it("returns '--' for null", () => {
    expect(formatPercent(null)).toBe("--");
  });
});

describe("formatDateTime", () => {
  it("returns formatted date for ISO string", () => {
    const result = formatDateTime("2025-06-15T14:30:00Z");
    expect(result).not.toBe("--");
    expect(result).toContain("2025");
  });

  it("returns '--' for null", () => {
    expect(formatDateTime(null)).toBe("--");
  });

  it("returns '--' for empty string", () => {
    expect(formatDateTime("")).toBe("--");
  });
});

describe("formatShortDate", () => {
  it("returns date without time", () => {
    const result = formatShortDate("2025-01-01T00:00:00Z");
    expect(result).not.toBe("--");
    expect(result).not.toContain(":");
  });
});

describe("formatMoney", () => {
  it("converts cents to CNY currency", () => {
    const result = formatMoney(2999, "CNY");
    expect(result).toContain("29.99");
  });

  it("returns '--' for null", () => {
    expect(formatMoney(null, "CNY")).toBe("--");
  });

  it("returns raw amount when no currency", () => {
    const result = formatMoney(5000, null);
    expect(result).toBe("50.00");
  });

  it("falls back gracefully for unknown currency", () => {
    const result = formatMoney(1000, "XYZ");
    expect(result).toContain("10.00");
    expect(result).toContain("XYZ");
  });
});

describe("trendSign", () => {
  it("returns positive sign for positive delta", () => {
    expect(trendSign(500)).toContain("+");
  });

  it("returns negative sign for negative delta", () => {
    const result = trendSign(-300);
    expect(result).toContain("-");
  });

  it("returns '--' for null", () => {
    expect(trendSign(null)).toBe("--");
  });

  it("returns '--' for zero", () => {
    expect(trendSign(0)).toBe("--");
  });
});
